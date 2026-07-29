"""Multi-hop QKD over a repeater chain: alice — repeater — bob.

Combines entanglement swapping with key distribution. Each round the repeater swaps
its two elementary links into one end-to-end pair; alice and bob then measure in a
random basis and run BBM92 sifting + QBER estimation, with all classical traffic
relayed (transparently) through the repeater. Demand signature: multi-hop / relay
*and* steady + fidelity-thresholded — two elementary pairs per key round, and the
key collapses when the swapped-pair QBER (which compounds both links' noise) crosses
threshold.

Topology: a 3-node star with `repeater` at the hub, built by default.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Basis, Demand, Gate, Host, Role
from qnetbench.apps.util import cfg_int


class MultihopQKD:
    name = "multihop_qkd"

    def __init__(
        self, rounds: int = 128, min_fidelity: float = 0.8, qber_threshold: float = 0.11
    ) -> None:
        self.rounds = rounds
        self.min_fidelity = min_fidelity
        self.qber_threshold = qber_threshold

    def roles(self) -> list[Role]:
        return ["repeater", "alice", "bob"]  # repeater = hub (role[0])

    def _demand(self) -> Demand:
        return Demand(min_fidelity=self.min_fidelity, purpose="keep")

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        rounds = cfg_int(cfg, "rounds", self.rounds)
        if role == "repeater":
            return self._repeater(host, rounds)
        return self._endpoint(host, role, rounds)

    def _repeater(self, host: Host, rounds: int) -> AppOutcome:
        epr_a, epr_b = host.epr_socket("alice"), host.epr_socket("bob")
        cls_a, cls_b = host.classical_socket("alice"), host.classical_socket("bob")
        for _ in range(rounds):  # swap each round; bob gets the correction
            r1 = epr_a.request(1, self._demand())[0].qubit
            r2 = epr_b.request(1, self._demand())[0].qubit
            assert r1 is not None and r2 is not None
            r1.cnot(r2)
            r1.apply(Gate.H)
            cls_b.send(bytes([r1.measure(Basis.Z), r2.measure(Basis.Z)]))
        # Reconciliation: relay alice<->bob classical (the repeater never sees the key).
        cls_b.send(cls_a.recv())  # alice's bases -> bob
        cls_a.send(cls_b.recv())  # bob's bases  -> alice
        cls_b.send(cls_a.recv())  # alice's test bits -> bob
        cls_a.send(cls_b.recv())  # bob's test bits   -> alice
        verdict = cls_a.recv()  # alice's (success, utility)
        return AppOutcome(
            role="repeater",
            success=bool(verdict[0]),
            utility=verdict[1] / 255.0,
            payload={"rounds": rounds},
        )

    def _endpoint(self, host: Host, role: Role, rounds: int) -> AppOutcome:
        epr = host.epr_socket("repeater")
        cls = host.classical_socket("repeater")
        bases: list[int] = []
        bits: list[int] = []
        for _ in range(rounds):
            qubit = epr.request(1, self._demand())[0].qubit
            assert qubit is not None
            if role == "bob":  # apply the swap correction before measuring
                m1, m2 = cls.recv()[:2]
                if m2:
                    qubit.apply(Gate.X)
                if m1:
                    qubit.apply(Gate.Z)
            use_x = host.rng.random() < 0.5
            bits.append(qubit.measure(Basis.X if use_x else Basis.Z))
            bases.append(1 if use_x else 0)

        # BBM92 sifting + QBER, classical relayed through the repeater.
        if role == "alice":
            cls.send(bytes(bases))
            their_bases = list(cls.recv())
        else:
            their_bases = list(cls.recv())
            cls.send(bytes(bases))
        sifted = [i for i in range(rounds) if bases[i] == their_bases[i]]
        test = [i for k, i in enumerate(sifted) if k % 2 == 0]
        keep = [i for k, i in enumerate(sifted) if k % 2 == 1]
        if role == "alice":
            cls.send(bytes(bits[i] for i in test))
            their_test = list(cls.recv())
        else:
            their_test = list(cls.recv())
            cls.send(bytes(bits[i] for i in test))
        errors = sum(1 for j, i in enumerate(test) if bits[i] != their_test[j])
        qber = errors / len(test) if test else 0.0

        key = [bits[i] for i in keep]
        success = qber <= self.qber_threshold and len(key) > 0
        utility = min(len(key) / rounds, 1.0) if success and rounds else 0.0
        if role == "alice":
            cls.send(bytes([1 if success else 0, round(utility * 255)]))
        return AppOutcome(
            role=role,
            success=success,
            utility=utility,
            payload={"qber": qber, "key_len": len(key)},
        )
