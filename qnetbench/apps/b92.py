"""B92 quantum key distribution (prepare-and-measure, two non-orthogonal states).

Alice encodes bit 0 as |0> and bit 1 as |+> — two *non-orthogonal* states — and
sends the qubit. Bob measures in a random basis. Because |+> never yields |-> in the
X basis and |0> never yields |1> in the Z basis, a "1" outcome is *conclusive*: a
Z-basis 1 means Alice sent bit 1, an X-basis 1 (|->) means she sent bit 0. Bob keeps
only the conclusive rounds (~1/4 of them); the rest are discarded.

Demand signature: single-qubit transmission (`qsend`/`qrecv`), like BB84 but with a
lower sifting yield. Utility is the secure key rate, which collapses when the channel
QBER crosses threshold.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Basis, Gate, Host, Role
from qnetbench.apps.util import cfg_int


class B92:
    name = "b92"

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
        bits = [int(host.rng.integers(0, 2)) for _ in range(rounds)]
        for bit in bits:
            qubit = host.qalloc()
            if bit:
                qubit.apply(Gate.H)  # bit 0 -> |0>, bit 1 -> |+>
            host.qsend("bob", qubit)
        # Per-round status: 0 inconclusive, 1 conclusive-bit0, 2 conclusive-bit1.
        status = list(cls.recv())
        alice_key = [bits[r] for r in range(rounds) if status[r]]
        return _reconcile(cls, alice_key, rounds, self.qber_threshold, "alice")

    def _receiver(self, host: Host, rounds: int) -> AppOutcome:
        cls = host.classical_socket("alice")
        status = bytearray(rounds)
        for r in range(rounds):
            qubit = host.qrecv("alice")
            measure_x = host.rng.random() < 0.5
            outcome = qubit.measure(Basis.X if measure_x else Basis.Z)
            host.record_measurement(Basis.X if measure_x else Basis.Z, outcome)
            if outcome == 1:  # conclusive: X-1 (|->) => bit 0; Z-1 (|1>) => bit 1
                status[r] = 1 + (0 if measure_x else 1)
        cls.send(bytes(status))
        bob_key = [b - 1 for b in status if b]
        return _reconcile(cls, bob_key, rounds, self.qber_threshold, "bob")


def _reconcile(cls, my_key, rounds, threshold, role) -> AppOutcome:  # type: ignore[no-untyped-def]
    # A public test subset estimates the QBER over the conclusive (sifted) bits.
    test = [k for k in range(len(my_key)) if k % 2 == 0]
    keep = [k for k in range(len(my_key)) if k % 2 == 1]
    if role == "alice":
        cls.send(bytes(my_key[k] for k in test))
        their_test = list(cls.recv())
    else:
        their_test = list(cls.recv())
        cls.send(bytes(my_key[k] for k in test))
    errors = sum(1 for j, k in enumerate(test) if my_key[k] != their_test[j])
    qber = errors / len(test) if test else 0.0

    key = [my_key[k] for k in keep]
    success = qber <= threshold and len(key) > 0
    utility = min(len(key) / rounds, 1.0) if success and rounds else 0.0
    return AppOutcome(
        role=role,
        success=success,
        utility=utility,
        payload={"qber": qber, "key_len": len(key), "conclusive": len(my_key)},
    )
