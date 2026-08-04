"""Entanglement-distillation (recurrence) primitives, shared by the distillation
and distilled-gate applications.

One recurrence step consumes two noisy pairs and yields at most one better pair.
Both nodes apply a bilateral CNOT from the pair they keep onto the pair they
sacrifice, measure the sacrificed half in Z, and compare outcomes over the classical
channel: agreement heralds success (the surviving pair is more entangled than either
input), disagreement means an error was detected and the kept pair is discarded.

The DEJMPS variant first rotates both local qubits by RX(±π/2) — *opposite* signs at
the two nodes — which permutes the Bell-diagonal weights so that phase errors become
flip errors, making the step strictly more effective than the plain bilateral CNOT.

Both nodes run the same step concurrently, differing only in the rotation sign.
"""

from __future__ import annotations

import math

from qnetbench.api import Basis, ClassicalSocket, Gate, Qubit

_HALF_PI = math.pi / 2


def distill_step(
    keep: Qubit,
    sacrifice: Qubit,
    cls: ClassicalSocket,
    *,
    sign: int = 1,
    dejmps: bool = True,
) -> bool:
    """Run one recurrence step on this node's halves of two pairs.

    `keep` and `sacrifice` are the local halves; the peer must call this
    concurrently with the matching halves and the opposite `sign`. Returns True if
    the step was heralded successful, in which case `keep` survives as a distilled
    pair. On False the caller must release `keep` — the step consumed its
    entanglement. `sacrifice` is always consumed.
    """
    if dejmps:
        keep.apply(Gate.RX, sign * _HALF_PI)
        sacrifice.apply(Gate.RX, sign * _HALF_PI)
    keep.cnot(sacrifice)
    outcome = sacrifice.measure(Basis.Z)
    cls.send(bytes([outcome]))
    return outcome == cls.recv()[0]


def correlation_test(qubit: Qubit, cls: ClassicalSocket, basis: Basis) -> bool:
    """Consume a pair to test it: both nodes measure in the same basis and compare.

    A perfect Φ+ is perfectly correlated in both Z and X, so agreement is the
    signature of a good pair and the disagreement rate estimates its error rate.
    Both nodes must call this with the same `basis`.
    """
    bit = qubit.measure(basis)
    cls.send(bytes([bit]))
    return bit == cls.recv()[0]


def test_basis(index: int) -> Basis:
    """Alternate Z/X across rounds so both error types are sampled, without
    spending a classical message to agree on a basis."""
    return Basis.Z if index % 2 == 0 else Basis.X
