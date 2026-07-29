"""Prepare-and-measure BB84 quantum key distribution.

The original BB84: Alice prepares each qubit in a random bit and a random basis
(Z or X) and *sends the qubit itself* over a quantum channel; Bob measures in a
random basis. Where their bases match they share a bit; a public subset estimates
the QBER. Unlike the entanglement-based QKD in this suite, no pair is ever shared —
this is the single-qubit-transmission demand class (`host.qsend`/`host.qrecv`), and
the only app that uses it.

Demand signature: steady and rate-hungry like QKD, but the demand is qubit
*transmissions*, not entangled pairs. Utility is the secure key rate, which collapses
when the channel QBER crosses threshold.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Basis, Gate, Host, Role
from qnetbench.apps.util import cfg_int

_PEER = {"alice": "bob", "bob": "alice"}


class BB84:
    name = "bb84"

    def __init__(self, rounds: int = 256, qber_threshold: float = 0.11) -> None:
        self.rounds = rounds
        self.qber_threshold = qber_threshold

    def roles(self) -> list[Role]:
        return ["alice", "bob"]  # alice = sender, bob = receiver

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        rounds = cfg_int(cfg, "rounds", self.rounds)
        if role == "alice":
            return self._sender(host, rounds)
        return self._receiver(host, rounds)

    def _sender(self, host: Host, rounds: int) -> AppOutcome:
        cls = host.classical_socket("bob")
        bases: list[int] = []  # 0 = Z, 1 = X
        bits: list[int] = []
        for _ in range(rounds):
            bit = int(host.rng.integers(0, 2))
            use_x = host.rng.random() < 0.5
            qubit = host.qalloc()
            if bit:
                qubit.apply(Gate.X)  # |0> or |1>
            if use_x:
                qubit.apply(Gate.H)  # rotate into the X basis: |+> or |->
            host.qsend("bob", qubit)  # blocks until Bob receives it
            bits.append(bit)
            bases.append(1 if use_x else 0)
        return self._reconcile(cls, bases, bits, rounds, first=True)

    def _receiver(self, host: Host, rounds: int) -> AppOutcome:
        cls = host.classical_socket("alice")
        bases: list[int] = []
        bits: list[int] = []
        for _ in range(rounds):
            qubit = host.qrecv("alice")
            use_x = host.rng.random() < 0.5
            if use_x:
                qubit.apply(Gate.H)  # measure in the X basis
            host.record_measurement(Basis.X if use_x else Basis.Z, 0)
            bits.append(qubit.measure(Basis.Z))
            bases.append(1 if use_x else 0)
        return self._reconcile(cls, bases, bits, rounds, first=False)

    def _reconcile(self, cls, bases, bits, rounds, first) -> AppOutcome:  # type: ignore[no-untyped-def]
        # Basis reconciliation + QBER estimation, identical on both sides.
        if first:
            cls.send(bytes(bases))
            their_bases = list(cls.recv())
        else:
            their_bases = list(cls.recv())
            cls.send(bytes(bases))
        sifted = [i for i in range(rounds) if bases[i] == their_bases[i]]
        test = [i for k, i in enumerate(sifted) if k % 2 == 0]
        keep = [i for k, i in enumerate(sifted) if k % 2 == 1]
        if first:
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
        role = "alice" if first else "bob"
        return AppOutcome(
            role=role,
            success=success,
            utility=utility,
            payload={"qber": qber, "key_len": len(key), "sifted": len(sifted)},
        )
