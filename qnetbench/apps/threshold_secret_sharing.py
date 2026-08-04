"""((3, 5)) threshold quantum secret sharing via the five-qubit code (Cleve–Gottesman–Lo).

A (k, n) threshold scheme lets *any* k shareholders reconstruct the secret while any
k-1 learn nothing — unlike the (n, n) `secret_sharing`, which needs everyone. A GHZ
state can't do this (tracing out one party of a phase-encoded GHZ leaves a state
independent of the secret), so a genuine threshold needs a code with redundancy. The
[[5, 1, 3]] perfect code is the canonical CGL example: distance 3 tolerates 2 erasures,
so any 3 of 5 shares reconstruct, and it saturates the no-cloning bound n < 2k (5 < 6).

Each round the dealer encodes a secret bit into the logical state |s_L>, keeps share 0,
and transmits shares 1–4 to the four players (`qsend`). A random authorized 3-subset
then reconstructs: for that subset there is a logical-Z representative — a tensor of
single-qubit Paulis supported on exactly those three qubits — so each holder measures
its qubit in the prescribed basis and the parity of the outcomes (XOR a fixed sign bit)
recovers s. Any two holders' reduced state is independent of s (verified offline), so
they learn nothing.

The encoder (H/CNOT only) and the per-subset reconstruction table were synthesized and
checked numerically against the [[5, 1, 3]] stabilizers; see the docstring above each
constant. Utility is the fraction of rounds the chosen subset reconstructs correctly,
which degrades with transmission fidelity (the four sent shares pick up channel noise).

Demand signature: single-qubit **transmission** (`qsend`), but multipartite — four
sends per round across a 5-node star (`dealer` at the hub), the highest party count of
the transmission-based apps.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Basis, Gate, Host, Role
from qnetbench.apps.util import cfg_int

# Clifford encoder preparing |0_L> of the [[5, 1, 3]] code from |00000>, synthesized by
# reducing the stabilizer tableau {XZZXI, IXZZX, XIXZZ, ZXIXZ, ZZZZZ} to {Z1..Z5} and
# reversing the gate list. |1_L> = X_L|0_L> = X on all five qubits. Each entry is
# (name, a, b): single-qubit gates act on `a` (b unused, -1); CNOT is control a -> target b.
_ENCODER: tuple[tuple[str, int, int], ...] = (
    ("H", 3, -1), ("H", 2, -1), ("H", 1, -1), ("H", 0, -1), ("H", 4, -1),
    ("CNOT", 3, 4), ("H", 4, -1), ("H", 3, -1), ("CNOT", 1, 3), ("H", 3, -1),
    ("H", 2, -1), ("CNOT", 1, 2), ("H", 2, -1), ("H", 4, -1), ("CNOT", 0, 4),
    ("H", 4, -1), ("H", 2, -1), ("CNOT", 0, 2), ("H", 2, -1),
    ("CNOT", 3, 4), ("CNOT", 2, 4), ("CNOT", 1, 4), ("CNOT", 0, 4),
)

# For each authorized 3-subset (sorted), the single-qubit measurement bases (one per
# member, in order) of a logical-Z representative supported on it, and a sign bit:
# recovered secret = (XOR of the three outcomes) XOR flip. Derived against the encoded
# states above; every 3-subset is authorized (distance 3 -> 2 erasures corrected).
_RECON: dict[tuple[int, int, int], tuple[str, int]] = {
    (0, 1, 2): ("YZY", 0),
    (0, 1, 3): ("XXZ", 0),
    (0, 1, 4): ("ZYY", 1),
    (0, 2, 3): ("ZXX", 0),
    (0, 2, 4): ("XZX", 0),
    (0, 3, 4): ("YYZ", 1),
    (1, 2, 3): ("YZY", 0),
    (1, 2, 4): ("XXZ", 1),
    (1, 3, 4): ("ZXX", 0),
    (2, 3, 4): ("YZY", 1),
}
_SUBSETS = list(_RECON)
_BASIS = {"X": Basis.X, "Y": Basis.Y, "Z": Basis.Z}
_SIT_OUT = 255  # basis byte telling a player it is not in this round's subset


class ThresholdSecretSharing:
    name = "threshold_secret_sharing"

    def __init__(self, rounds: int = 64, min_fidelity: float = 0.9) -> None:
        self.rounds = rounds
        self.min_fidelity = min_fidelity

    def roles(self) -> list[Role]:
        # dealer holds share 0 (hub); player i holds share i.
        return ["dealer", "player1", "player2", "player3", "player4"]

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        rounds = cfg_int(cfg, "rounds", self.rounds)
        if role == "dealer":
            return self._dealer(host, rounds)
        return self._player(host, role, rounds)

    def _dealer(self, host: Host, rounds: int) -> AppOutcome:
        players = [f"player{i}" for i in range(1, 5)]
        cls = [host.classical_socket(p) for p in players]
        correct = 0
        for _ in range(rounds):
            qubits = [host.qalloc() for _ in range(5)]
            for name, a, b in _ENCODER:
                if name == "CNOT":
                    qubits[a].cnot(qubits[b])
                else:
                    qubits[a].apply(Gate.H)
            secret = int(host.rng.integers(0, 2))
            if secret:
                for q in qubits:
                    q.apply(Gate.X)  # X_L: |0_L> -> |1_L>
            for i in range(4):
                host.qsend(players[i], qubits[i + 1])  # share i+1 to player i+1

            subset = _SUBSETS[int(host.rng.integers(0, len(_SUBSETS)))]
            bases, flip = _RECON[subset]
            basis_of = {m: bases[k] for k, m in enumerate(subset)}
            for i, sock in enumerate(cls):
                share = i + 1
                sock.send(bytes([_encode_basis(basis_of[share]) if share in subset else _SIT_OUT]))

            # dealer's own share 0, measured only if it is in the subset
            own = qubits[0].measure(_BASIS[basis_of[0]] if 0 in subset else Basis.Z)
            replies = [sock.recv()[0] for sock in cls]  # every player answers (0 if sitting out)
            parity = (own if 0 in subset else 0)
            for share in subset:
                if share != 0:
                    parity ^= replies[share - 1]
            if (parity ^ flip) == secret:
                correct += 1
        for sock in cls:
            sock.send(bytes([correct >> 8, correct & 0xFF]))
        return _outcome("dealer", correct, rounds)

    def _player(self, host: Host, role: Role, rounds: int) -> AppOutcome:
        cls = host.classical_socket("dealer")
        for _ in range(rounds):
            share = host.qrecv("dealer")
            code = cls.recv()[0]
            if code == _SIT_OUT:
                share.measure(Basis.Z)  # free the qubit; outcome discarded
                cls.send(b"\x00")
            else:
                basis = _CODE_BASIS[code]
                outcome = share.measure(basis)
                host.record_measurement(basis, outcome)
                cls.send(bytes([outcome]))
        tally = cls.recv()
        return _outcome(role, (tally[0] << 8) | tally[1], rounds)


_CODE_BASIS = {0: Basis.Z, 1: Basis.X, 2: Basis.Y}
_BASIS_CODE = {"Z": 0, "X": 1, "Y": 2}


def _encode_basis(char: str) -> int:
    return _BASIS_CODE[char]


def _outcome(role: Role, correct: int, rounds: int) -> AppOutcome:
    return AppOutcome(
        role=role,
        success=correct == rounds,
        utility=correct / rounds if rounds else 0.0,
        payload={"rounds": rounds, "correct": correct},
    )
