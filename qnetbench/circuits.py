"""A tiny distributed-circuit IR and a circuit library for the DQC benchmark.

A `Circuit` is qubits assigned to nodes (`partition`) plus a list of `Op`s. The DQC
application executes it across those nodes: local gates apply directly, and every
*non-local* two-qubit gate becomes a teleported gate — an entanglement request with
a deadline derived from the gate's depth in the circuit. So a compiled circuit's
structure becomes an Entanglement Demand Schedule.

Library circuits are built as **mirror circuits** — a forward unitary U followed by
its exact inverse U† — so a noiseless run returns to |0…0> and every qubit measures
0. That makes any circuit verifiable, and it degrades cleanly as teleported-gate
fidelity drops. Gates are restricted to ones that invert by self (H, X, Y, Z, CNOT,
CZ) or by angle negation (RX/RY/RZ), so U† is built by reversing U and inverting
each op.

An optional `from_qiskit` loader (behind the `mqt` extra) turns a Qiskit / MQT Bench
circuit into this IR.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

ONE_QUBIT = {"H", "X", "Y", "Z", "S", "T", "RX", "RY", "RZ"}
TWO_QUBIT = {"CNOT", "CZ"}
_SELF_INVERSE = {"H", "X", "Y", "Z", "CNOT", "CZ"}


@dataclass(frozen=True)
class Op:
    gate: str  # a name in ONE_QUBIT or TWO_QUBIT
    qubits: tuple[int, ...]  # 1 or 2 qubit indices
    params: tuple[float, ...] = ()


def inverse_op(op: Op) -> Op:
    if op.gate in _SELF_INVERSE:
        return op
    if op.gate in {"RX", "RY", "RZ"}:
        return Op(op.gate, op.qubits, (-op.params[0],))
    raise ValueError(f"gate {op.gate!r} is not invertible in this IR (avoid S/T in circuits)")


@dataclass
class Circuit:
    n_qubits: int
    partition: tuple[int, ...]  # partition[q] = node index owning qubit q
    ops: list[Op] = field(default_factory=list)
    name: str = "circuit"

    def is_nonlocal(self, op: Op) -> bool:
        """True if `op` is a two-qubit gate whose qubits live on different nodes."""
        return len(op.qubits) == 2 and self.partition[op.qubits[0]] != self.partition[op.qubits[1]]

    def layers(self) -> list[int]:
        """ASAP schedule: the layer (1-indexed) each op executes in. A gate sits one
        layer after the latest gate on any of its qubits."""
        last = [0] * self.n_qubits
        out: list[int] = []
        for op in self.ops:
            layer = 1 + max(last[q] for q in op.qubits)
            out.append(layer)
            for q in op.qubits:
                last[q] = layer
        return out

    def depth(self) -> int:
        layers = self.layers()
        return max(layers) if layers else 0

    def n_nonlocal(self) -> int:
        return sum(1 for op in self.ops if self.is_nonlocal(op))


def mirror(ops: list[Op]) -> list[Op]:
    """U followed by U† — a circuit that returns |0…0> to |0…0> noiselessly."""
    return ops + [inverse_op(op) for op in reversed(ops)]


def _interleaved(n: int) -> tuple[int, ...]:
    """Alternate qubits between two nodes, so nearest-neighbour gates are non-local
    (maximising entanglement demand)."""
    return tuple(q % 2 for q in range(n))


def ghz(n: int = 4) -> Circuit:
    """GHZ preparation (H + CNOT chain) mirrored back to |0…0>."""
    fwd = [Op("H", (0,))] + [Op("CNOT", (i, i + 1)) for i in range(n - 1)]
    return Circuit(n, _interleaved(n), mirror(fwd), name=f"ghz{n}")


def _cphase(control: int, target: int, theta: float) -> list[Op]:
    """Controlled-phase decomposed into CNOTs + RZ (so it survives the invertible-gate
    restriction and turns non-local CPs into teleported CNOTs)."""
    return [
        Op("RZ", (control,), (theta / 2,)),
        Op("RZ", (target,), (theta / 2,)),
        Op("CNOT", (control, target)),
        Op("RZ", (target,), (-theta / 2,)),
        Op("CNOT", (control, target)),
    ]


def qft(n: int = 4) -> Circuit:
    """Quantum Fourier transform (H + controlled phases) mirrored back to |0…0>."""
    fwd: list[Op] = []
    for i in range(n):
        fwd.append(Op("H", (i,)))
        for j in range(i + 1, n):
            fwd += _cphase(i, j, math.pi / (2 ** (j - i)))
    return Circuit(n, _interleaved(n), mirror(fwd), name=f"qft{n}")


def random_circuit(n: int = 4, depth: int = 6, seed: int = 0) -> Circuit:
    """A random invertible circuit mirrored back to |0…0>."""
    rng = np.random.default_rng(seed)
    fwd: list[Op] = []
    for _ in range(depth):
        for q in range(n):  # a single-qubit gate on each qubit
            if rng.random() < 0.5:
                fwd.append(Op("H", (q,)))
            else:
                fwd.append(Op("RZ", (q,), (float(rng.uniform(0, 2 * math.pi)),)))
        order = rng.permutation(n)  # a layer of disjoint CNOTs
        for a, b in zip(order[::2], order[1::2], strict=False):
            fwd.append(Op("CNOT", (int(a), int(b))))
    return Circuit(n, _interleaved(n), mirror(fwd), name=f"random{n}")


def graph_state(n: int = 4) -> Circuit:
    """A ring graph state (H on all + CZ on nearest neighbours) mirrored to |0…0>."""
    fwd = [Op("H", (q,)) for q in range(n)]
    fwd += [Op("CZ", (i, i + 1)) for i in range(n - 1)]
    if n > 2:
        fwd.append(Op("CZ", (n - 1, 0)))  # close the ring
    return Circuit(n, _interleaved(n), mirror(fwd), name=f"graph{n}")


def iqp(n: int = 4, seed: int = 0) -> Circuit:
    """An instantaneous-quantum-polynomial circuit (H · diagonal · H) mirrored to |0…0>."""
    rng = np.random.default_rng(seed)
    diag: list[Op] = []
    for q in range(n):
        diag.append(Op("RZ", (q,), (float(rng.uniform(0, 2 * math.pi)),)))
    diag += [Op("CZ", (i, i + 1)) for i in range(n - 1)]
    fwd = [Op("H", (q,)) for q in range(n)] + diag + [Op("H", (q,)) for q in range(n)]
    return Circuit(n, _interleaved(n), mirror(fwd), name=f"iqp{n}")


def hea(n: int = 4, depth: int = 3, seed: int = 0) -> Circuit:
    """A hardware-efficient ansatz (RY rotations + CNOT entangling layers) mirrored to |0…0>."""
    rng = np.random.default_rng(seed)
    fwd: list[Op] = []
    for _ in range(depth):
        for q in range(n):
            fwd.append(Op("RY", (q,), (float(rng.uniform(0, 2 * math.pi)),)))
        fwd += [Op("CNOT", (i, i + 1)) for i in range(n - 1)]
    return Circuit(n, _interleaved(n), mirror(fwd), name=f"hea{n}")


def from_qiskit(qc: Any, partition: tuple[int, ...] | None = None, name: str = "qiskit") -> Circuit:
    """Convert a Qiskit `QuantumCircuit` (e.g. from MQT Bench) into this IR.

    Requires the optional `mqt`/`qiskit` extra. Only the gates in ONE_QUBIT/TWO_QUBIT
    are supported; a circuit using others raises `ValueError`. Not mirrored — verify
    such circuits by comparison against a local run rather than the |0…0> property.
    (Typed `Any` because Qiskit is an optional dependency this module never imports.)
    """
    alias = {"cx": "CNOT", "cz": "CZ", "h": "H", "x": "X", "y": "Y", "z": "Z",
             "s": "S", "t": "T", "rx": "RX", "ry": "RY", "rz": "RZ"}
    ops: list[Op] = []
    for instruction in qc.data:
        gate = instruction.operation.name.lower()
        if gate not in alias:
            raise ValueError(f"unsupported gate {gate!r}; supported: {sorted(alias)}")
        indices = tuple(qc.find_bit(q).index for q in instruction.qubits)
        params = tuple(float(p) for p in instruction.operation.params)
        ops.append(Op(alias[gate], indices, params))
    return Circuit(qc.num_qubits, partition or _interleaved(qc.num_qubits), ops, name=name)
