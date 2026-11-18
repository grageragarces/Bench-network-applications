"""A minimal statevector simulator for the reference backend.

Just enough quantum mechanics to make application invariants real: BB84 QBER,
the teleported-CNOT truth table, and CHSH's S = 2√2. Entangled pairs span nodes,
so a single global register holds every live qubit; positions are tiny (a handful
at a time), so a full 2^n statevector is more than fast enough.

Qubit ordering is MSB-first: position 0 is the most significant bit of the index.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

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


MemoryNoise = Literal["dephasing", "depolarizing"]


@dataclass
class _Memory:
    """Decoherence of stored qubits, applied lazily when a qubit is next used."""

    clock: Callable[[], float]
    coherence_time: float
    noise: MemoryNoise
    rng: np.random.Generator
    last: dict[int, float] = field(default_factory=dict)  # when each qubit was last settled
    owner: dict[int, str] = field(default_factory=dict)  # which node holds each qubit


class Register:
    """A growable global statevector over uniquely-identified qubits."""

    def __init__(self, rng: np.random.Generator) -> None:
        self._rng = rng
        self._ids: list[int] = []
        self._state = np.ones(1, dtype=complex)  # zero-qubit register = scalar 1
        self._next_id = 0
        self._memory: _Memory | None = None  # off unless `enable_memory` is called

    # --- memory: off by default, and then these methods do nothing and draw nothing ---

    def enable_memory(
        self,
        clock: Callable[[], float],
        coherence_time: float,
        noise: MemoryNoise,
        rng: np.random.Generator,
    ) -> None:
        """Make stored qubits decay with per-qubit time constant `coherence_time`. `rng`
        is a separate stream, so this noise does not move the measurement stream."""
        self._memory = _Memory(clock, coherence_time, noise, rng)

    def stamp(self, qid: int, when: float, node: str) -> None:
        """Record that `node` holds `qid`, and that it starts decaying at `when`."""
        if self._memory is not None:
            self._memory.last[qid] = when
            self._memory.owner[qid] = node

    def reassign(self, qid: int, node: str) -> None:
        """A qubit moved to another node. Its decay clock keeps running."""
        if self._memory is not None:
            self._memory.owner[qid] = node

    def pause(self, node: str, duration: float) -> None:
        """Do not charge `duration` to the qubits `node` holds."""
        if self._memory is not None:
            for qid, holder in self._memory.owner.items():
                if holder == node and qid in self._ids:
                    self._memory.last[qid] += duration

    def aged_fidelity(self, fidelity: float, age: float) -> float:
        """The fidelity of a pair after both halves have been stored for `age` seconds.

        What `settle` does to a pair, in closed form, for reporting it at delivery. With
        p = (4F - 1) / 3, both channels shrink p or its phase part by exp(-2 age / T).
        Dephasing leaves Z correlations alone, so it levels off near F = 1/2, not 1/4.
        """
        memory = self._memory
        if memory is None or age <= 0.0 or math.isinf(memory.coherence_time):
            return fidelity
        survival = math.exp(-2.0 * age / memory.coherence_time)
        weight = (4.0 * fidelity - 1.0) / 3.0
        if memory.noise == "dephasing":
            return fidelity - (1.0 - survival) / 2.0 * weight
        return (1.0 + 3.0 * weight * survival) / 4.0

    def settle(self, qid: int) -> None:
        """Apply the decay accumulated since this qubit was last settled.

        Unravelled as a random Pauli, like `make_bell_pair`. Both channels compose over
        intervals, so settling at each use is the same as settling continuously.
        """
        memory = self._memory
        if memory is None or math.isinf(memory.coherence_time):
            return
        now = memory.clock()
        elapsed = now - memory.last.get(qid, now)
        memory.last[qid] = max(now, memory.last.get(qid, now))
        if elapsed <= 0.0:
            return
        survival = math.exp(-elapsed / memory.coherence_time)
        if memory.noise == "dephasing":
            if memory.rng.random() < (1.0 - survival) / 2.0:
                self.apply_1q(qid, _Z)
        elif memory.rng.random() >= survival:
            self.apply_1q(qid, _PAULIS[memory.rng.integers(0, 4)])

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
        # CNOT just permutes basis amplitudes: where the control bit is set, the
        # target bit flips. Build that permutation of indices and reorder the state.
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

        # Sample the outcome from the probability of the qubit being |1>.
        pos, n = self._pos(qid), self.n
        probs = np.abs(self._state) ** 2
        p1 = float(sum(probs[i] for i in range(2**n) if self._bit(i, pos)))
        outcome = 1 if self._rng.random() < p1 else 0
        if (outcome == 1 and p1 == 0.0) or (outcome == 0 and p1 == 1.0):
            outcome = 1 - outcome  # guard a numerically impossible sample

        # Project onto the outcome by slicing that qubit's axis, renormalize the
        # surviving amplitudes, and drop the axis — the qubit is now gone.
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

    def depolarize(self, qid: int, fidelity: float) -> None:
        """Send a single qubit through a depolarizing channel of the given fidelity:
        with probability (1 - fidelity) apply a random Pauli. Used for single-qubit
        transmission (prepare-and-measure protocols)."""
        if fidelity < 1.0 and self._rng.random() >= fidelity:
            self.apply_1q(qid, _PAULIS[self._rng.integers(1, 4)])  # X, Y, or Z

    def make_bell_pair(
        self, fidelity: float, weights: tuple[float, float, float, float] | None = None
    ) -> tuple[int, int]:
        """Create a noisy Φ+ pair at the given fidelity; return (id_a, id_b).

        With `weights=None` the pair is a Werner state: its maximally-mixed part is
        unravelled as a random Pauli twirl on one half, so many shots reproduce the
        Werner state's statistics with a pure register.

        `weights` gives any Bell-diagonal state instead, as the probabilities of
        (Φ+, Ψ+, Φ-, Ψ-). One of I, X, Z or Y is applied to the second half with those
        probabilities, which turns Φ+ into the corresponding Bell state.
        """
        a, b = self.alloc(), self.alloc()
        self.apply_1q(a, _H)
        self.cnot(a, b)
        if weights is not None:
            k = int(self._rng.choice(4, p=np.asarray(weights) / sum(weights)))
            if k:
                self.apply_1q(b, (_X, _Z, _Y)[k - 1])
            return a, b
        p = (4.0 * fidelity - 1.0) / 3.0  # Werner weight of the ideal Bell state
        p = min(max(p, 0.0), 1.0)
        if self._rng.random() >= p:
            self.apply_1q(b, _PAULIS[self._rng.integers(0, 4)])
        return a, b
