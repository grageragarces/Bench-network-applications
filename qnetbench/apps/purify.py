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
    """Cycle Z/X/Y across rounds, without spending a classical message to agree.

    Three bases rather than two because two do not identify the state. Agreement
    rates in Z and X alone give p(Phi+) + p(Phi-) and p(Phi+) + p(Psi+), which
    leaves the weight on Phi+ — the quantity that says whether the pair is
    entangled at all — undetermined. Adding Y closes the system; see
    `singlet_fraction`.
    """
    return (Basis.Z, Basis.X, Basis.Y)[index % 3]


def singlet_fraction(agree: dict[Basis, tuple[int, int]]) -> float:
    """Fidelity to Phi+ estimated from same-basis agreement rates.

    For a Bell-diagonal state with weights (p1, p2, p3, p4) on
    (Phi+, Phi-, Psi+, Psi-), measuring both halves in the same basis and
    comparing gives

        a_Z = p1 + p2,   a_X = p1 + p3,   a_Y = p2 + p3,

    so p1 = (a_Z + a_X - a_Y) / 2. This is the quantity that matters for a
    distillation protocol: a two-qubit state is entangled exactly when its
    singlet fraction exceeds 1/2, so an output at 0.5 is a classically
    correlated pair and not a distilled one, however well it agrees in any
    single basis.

    `agree` maps each basis to (agreements, trials). Returns 0.0 if any basis
    went unsampled; clamps to [0, 1], since the estimator is unbiased but noisy.
    """
    rates = {}
    for basis in (Basis.Z, Basis.X, Basis.Y):
        ok, n = agree.get(basis, (0, 0))
        if n == 0:
            return 0.0
        rates[basis] = ok / n
    p1 = (rates[Basis.Z] + rates[Basis.X] - rates[Basis.Y]) / 2
    return min(1.0, max(0.0, p1))
