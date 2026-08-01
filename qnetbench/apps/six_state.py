"""Six-state quantum key distribution (prepare-and-measure, three bases).

Like BB84 but with three mutually-unbiased bases — Z, X, and Y. Alice prepares each
qubit in a random bit and a random one of the three bases and sends it; Bob measures
in a random basis; they sift the rounds whose bases matched. Using all three bases
gives six signal states (hence the name) and a higher tolerable error rate than BB84,
at the cost of a lower sifting yield (1/3 of rounds match instead of 1/2).

Demand signature: single-qubit transmission (`qsend`/`qrecv`), steady and
fidelity-thresholded. Utility is the secure key rate.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Basis, Gate, Host, Role
from qnetbench.apps.util import cfg_int

_BASES = (Basis.Z, Basis.X, Basis.Y)  # 0 = Z, 1 = X, 2 = Y
_PEER = {"alice": "bob", "bob": "alice"}


class SixState:
    name = "six_state"

    def __init__(self, rounds: int = 300, qber_threshold: float = 0.126) -> None:
        self.rounds = rounds
        self.qber_threshold = qber_threshold  # six-state tolerates a higher QBER than BB84

    def roles(self) -> list[Role]:
        return ["alice", "bob"]  # alice = sender, bob = receiver

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        rounds = cfg_int(cfg, "rounds", self.rounds)
        if role == "alice":
            return self._sender(host, rounds)
        return self._receiver(host, rounds)

    def _sender(self, host: Host, rounds: int) -> AppOutcome:
        cls = host.classical_socket("bob")
        bases: list[int] = []
        bits: list[int] = []
        for _ in range(rounds):
            bit = int(host.rng.integers(0, 2))
            basis = int(host.rng.integers(0, 3))
            qubit = host.qalloc()
            if bit:
                qubit.apply(Gate.X)
            if basis == 1:  # X: |+>/|->
                qubit.apply(Gate.H)
            elif basis == 2:  # Y: |+i>/|-i> = S·H|bit>
                qubit.apply(Gate.H)
                qubit.apply(Gate.S)
            host.qsend("bob", qubit)
            bases.append(basis)
            bits.append(bit)
        return self._reconcile(cls, bases, bits, rounds, first=True)

    def _receiver(self, host: Host, rounds: int) -> AppOutcome:
        cls = host.classical_socket("alice")
        bases: list[int] = []
        bits: list[int] = []
        for _ in range(rounds):
            qubit = host.qrecv("alice")
            basis = int(host.rng.integers(0, 3))
            bits.append(qubit.measure(_BASES[basis]))
            host.record_measurement(_BASES[basis], bits[-1])
            bases.append(basis)
        return self._reconcile(cls, bases, bits, rounds, first=False)

    def _reconcile(self, cls, bases, bits, rounds, first) -> AppOutcome:  # type: ignore[no-untyped-def]
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
        return AppOutcome(
            role="alice" if first else "bob",
            success=success,
            utility=utility,
            payload={"qber": qber, "key_len": len(key), "sifted": len(sifted)},
        )
