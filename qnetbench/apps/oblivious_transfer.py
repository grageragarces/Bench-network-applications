"""1-out-of-2 quantum oblivious transfer (BBCS, bounded/noisy-storage model).

Alice holds two secret bits; Bob learns exactly one of them, of his choosing, and
Alice never learns which. This is the *secure two-party computation* class — the
primitive from which general two-party secure computation is built — and it is the
first protocol in the suite whose goal is neither a shared key, a delegated
computation, nor a distributed gate.

Alice transmits BB84 states; Bob measures each in a random basis. When Alice later
announces her bases, Bob knows his outcome is correct exactly on the indices where
the bases matched. He partitions the indices into two sets, putting the matched ones
in the set for the bit he wants, and Alice masks each secret with the parity of her
bits on the corresponding set. Bob can unmask the set he measured correctly and gets
no information about the other, whose parity is uniformly random to him.

Demand signature: single-qubit transmission (`qsend`/`qrecv`) like the
prepare-and-measure key protocols, but with a batched, structurally deeper classical
phase — the transfer cannot begin until the whole quantum phase is complete, so its
classical coupling is low per qubit yet strictly ordered.

Utility is the fraction of transfers Bob decoded correctly; the payload records how
often he could have guessed the *other* secret, which should sit at chance.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Basis, ClassicalSocket, Gate, Host, Role
from qnetbench.apps.util import cfg_int


class ObliviousTransfer:
    name = "oblivious_transfer"

    def __init__(self, transfers: int = 16, qubits: int = 32, block: int = 8) -> None:
        self.transfers = transfers
        self.qubits = qubits
        # Each secret is masked with the parity of a fixed-size *block* of the set
        # rather than the whole set. A parity over tens of noisy bits is a coin flip
        # (the error rate compounds), which would make the protocol a step function
        # at F = 1; a bounded block degrades smoothly with channel quality, which is
        # what the fidelity-sensitivity curve needs to resolve.
        self.block = block

    def roles(self) -> list[Role]:
        return ["alice", "bob"]  # alice = sender, bob = receiver

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        transfers = cfg_int(cfg, "transfers", self.transfers)
        qubits = cfg_int(cfg, "qubits", self.qubits)
        if role == "alice":
            return self._sender(host, transfers, qubits)
        return self._receiver(host, transfers, qubits)

    def _sender(self, host: Host, transfers: int, qubits: int) -> AppOutcome:
        cls = host.classical_socket("bob")
        for _ in range(transfers):
            bits: list[int] = []
            bases: list[int] = []  # 0 = Z, 1 = X
            for _ in range(qubits):
                bit = int(host.rng.integers(0, 2))
                use_x = host.rng.random() < 0.5
                qubit = host.qalloc()
                if bit:
                    qubit.apply(Gate.X)
                if use_x:
                    qubit.apply(Gate.H)
                host.qsend("bob", qubit)
                bits.append(bit)
                bases.append(int(use_x))

            cls.send(bytes(bases))  # the quantum phase is over; reveal the bases
            assignment = list(cls.recv())  # Bob's partition: index -> set 0 or 1

            # Mask each secret with the parity of Alice's bits on that set. Alice
            # cannot tell which set Bob measured correctly, so she learns nothing
            # about his choice.
            secrets = [int(host.rng.integers(0, 2)), int(host.rng.integers(0, 2))]
            masked = [
                secrets[s] ^ _parity(bits, _block(assignment, s, self.block)) for s in (0, 1)
            ]
            cls.send(bytes(masked + secrets))  # secrets travel for scoring only

        correct = _recv_count(cls)
        return _outcome("alice", correct, transfers, 0)

    def _receiver(self, host: Host, transfers: int, qubits: int) -> AppOutcome:
        cls = host.classical_socket("alice")
        correct = 0
        other_guessed = 0
        for _ in range(transfers):
            bits: list[int] = []
            bases: list[int] = []
            for _ in range(qubits):
                qubit = host.qrecv("alice")
                use_x = host.rng.random() < 0.5
                if use_x:
                    qubit.apply(Gate.H)
                bits.append(qubit.measure(Basis.Z))
                bases.append(int(use_x))
                host.record_measurement(Basis.X if use_x else Basis.Z, bits[-1])

            their_bases = list(cls.recv())
            choice = int(host.rng.integers(0, 2))  # the bit Bob wants
            # Matched-basis indices are the ones Bob measured correctly: put them in
            # the set for the secret he wants, and the rest in the other set.
            assignment = [
                choice if bases[i] == their_bases[i] else 1 - choice for i in range(qubits)
            ]
            cls.send(bytes(assignment))

            payload = cls.recv()
            masked, secrets = list(payload[:2]), list(payload[2:4])
            got = masked[choice] ^ _parity(bits, _block(assignment, choice, self.block))
            correct += int(got == secrets[choice])
            # The other set is all mismatched-basis indices, so its parity is
            # uniformly random to Bob: this should land at chance, not at 1.
            other = masked[1 - choice] ^ _parity(bits, _block(assignment, 1 - choice, self.block))
            other_guessed += int(other == secrets[1 - choice])

        cls.send(bytes([correct >> 8, correct & 0xFF]))
        return _outcome("bob", correct, transfers, other_guessed)


def _block(assignment: list[int], which: int, size: int) -> list[int]:
    """The first `size` indices Bob assigned to set `which`. Both nodes derive this
    from the announced assignment, so no extra message is needed to agree on it."""
    return [i for i, s in enumerate(assignment) if s == which][:size]


def _parity(bits: list[int], indices: list[int]) -> int:
    total = 0
    for i in indices:
        total ^= bits[i]
    return total


def _recv_count(cls: ClassicalSocket) -> int:
    tally = cls.recv()
    return (tally[0] << 8) | tally[1]


def _outcome(role: Role, correct: int, transfers: int, other_guessed: int) -> AppOutcome:
    return AppOutcome(
        role=role,
        success=correct == transfers,
        utility=correct / transfers if transfers else 0.0,
        payload={
            "transfers": transfers,
            "correct": correct,
            "other_guessed": other_guessed,
        },
    )
