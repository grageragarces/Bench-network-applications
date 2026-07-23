"""A minimal statevector simulator for the reference backend.

Just enough quantum mechanics to make application invariants real: BB84 QBER,
the teleported-CNOT truth table, and CHSH's S = 2√2. Entangled pairs span nodes,
so a single global register holds every live qubit; positions are tiny (a handful
at a time), so a full 2^n statevector is more than fast enough.

Qubit ordering is MSB-first: position 0 is the most significant bit of the index.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

I2 = np.array([[1, 0], [0, 1]], dtype=complex)
_X = np.array([[0, 1], [1, 0]], dtype=complex)
_Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
_Z = np.array([[1, 0], [0, -1]], dtype=complex)
_H = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
_S = np.array([[1, 0], [0, 1j]], dtype=complex)
_SDG = np.array([[1, 0], [0, -1j]], dtype=complex)
_T = np.array([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=complex)

_STATIC: dict[str, NDArray[np.complex128]] = {
    "I": I2,
    "X": _X,
    "Y": _Y,
    "Z": _Z,
    "H": _H,
    "S": _S,
    "T": _T,
}
_PAULIS = [I2, _X, _Y, _Z]


def _rx(theta: float) -> NDArray[np.complex128]:
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array([[c, -1j * s], [-1j * s, c]], dtype=complex)


def _ry(theta: float) -> NDArray[np.complex128]:
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array([[c, -s], [s, c]], dtype=complex)


def _rz(theta: float) -> NDArray[np.complex128]:
    return np.array([[np.exp(-1j * theta / 2), 0], [0, np.exp(1j * theta / 2)]], dtype=complex)


def gate_matrix(name: str, params: tuple[float, ...]) -> NDArray[np.complex128]:
    if name in _STATIC:
        return _STATIC[name]
    if name == "RX":
        return _rx(params[0])
    if name == "RY":
        return _ry(params[0])
    if name == "RZ":
        return _rz(params[0])
    raise ValueError(f"unknown gate {name!r}")


class Register:
    """A growable global statevector over uniquely-identified qubits."""

    def __init__(self, rng: np.random.Generator) -> None:
        self._rng = rng
        self._ids: list[int] = []
        self._state = np.ones(1, dtype=complex)  # zero-qubit register = scalar 1
        self._next_id = 0

    @property
    def n(self) -> int:
        return len(self._ids)

    def _pos(self, qid: int) -> int:
        return self._ids.index(qid)

    def alloc(self) -> int:
        """Allocate a fresh |0> qubit; returns its id."""
        qid = self._next_id
        self._next_id += 1
        self._ids.append(qid)
        self._state = np.kron(self._state, np.array([1, 0], dtype=complex))
        return qid

    def apply_1q(self, qid: int, matrix: NDArray[np.complex128]) -> None:
        pos, n = self._pos(qid), self.n
        psi = self._state.reshape([2] * n)
        psi = np.tensordot(matrix, psi, axes=([1], [pos]))
        psi = np.moveaxis(psi, 0, pos)
        self._state = psi.reshape(2**n)

    def _bit(self, index: int, pos: int) -> int:
        return (index >> (self.n - 1 - pos)) & 1

    def cnot(self, control: int, target: int) -> None:
        c, t, n = self._pos(control), self._pos(target), self.n
        perm = np.arange(2**n)
        for i in range(2**n):
            if self._bit(i, c):
                perm[i] = i ^ (1 << (n - 1 - t))
        self._state = self._state[np.argsort(perm)]

    def cz(self, control: int, target: int) -> None:
        c, t, n = self._pos(control), self._pos(target), self.n
        for i in range(2**n):
            if self._bit(i, c) and self._bit(i, t):
                self._state[i] = -self._state[i]

    def measure(self, qid: int, basis: str = "Z") -> int:
        """Destructively measure a qubit: sample an outcome, collapse the register
        onto it, and drop the qubit (as real network stacks free the physical
        qubit on measurement). This also keeps the global statevector small."""
        if basis == "X":
            self.apply_1q(qid, _H)
        elif basis == "Y":
            self.apply_1q(qid, _SDG)
            self.apply_1q(qid, _H)
        elif basis != "Z":
            raise ValueError(f"unknown basis {basis!r}")

        pos, n = self._pos(qid), self.n
        probs = np.abs(self._state) ** 2
        p1 = float(sum(probs[i] for i in range(2**n) if self._bit(i, pos)))
        outcome = 1 if self._rng.random() < p1 else 0
        if (outcome == 1 and p1 == 0.0) or (outcome == 0 and p1 == 1.0):
            outcome = 1 - outcome  # guard a numerically impossible sample

        psi = self._state.reshape([2] * n)
        sl: list[int | slice] = [slice(None)] * n
        sl[pos] = outcome
        reduced = np.asarray(psi[tuple(sl)]).reshape(2 ** (n - 1))
        norm = float(np.linalg.norm(reduced))
        self._state = reduced / norm
        self._ids.pop(pos)
        return outcome

    def free(self, qid: int) -> None:
        """Discard a qubit by measuring it out (result ignored)."""
        self.measure(qid, "Z")

    def make_bell_pair(self, fidelity: float) -> tuple[int, int]:
        """Create a Werner-noised Φ+ pair at the given fidelity; return (id_a, id_b).

        The maximally-mixed part is unravelled as a random Pauli twirl on one half,
        so many shots reproduce the Werner state's statistics with a pure register.
        """
        a, b = self.alloc(), self.alloc()
        self.apply_1q(a, _H)
        self.cnot(a, b)
        p = (4.0 * fidelity - 1.0) / 3.0  # Werner weight of the ideal Bell state
        p = min(max(p, 0.0), 1.0)
        if self._rng.random() >= p:
            self.apply_1q(b, _PAULIS[self._rng.integers(0, 4)])
        return a, b
