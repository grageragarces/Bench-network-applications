"""The teleported (non-local) CNOT primitive — one shared EPR pair + two classical
bits apply a CNOT whose control and target live on different nodes (the
Gottesman–Chuang cat-entangler/disentangler). Shared by the distributed-gate app
and the DQC executor.

The two halves run concurrently on the two nodes: the control side calls
`telegate_control` on its qubit, the target side calls `telegate_target` on its
qubit, with an EPR socket and classical socket to each other.
"""

from __future__ import annotations

from qnetbench.api import Basis, ClassicalSocket, Demand, EPRSocket, Gate, Qubit


def telegate_control(control: Qubit, epr: EPRSocket, cls: ClassicalSocket, demand: Demand) -> None:
    """Apply CNOT with `control` here onto a remote target, via one EPR pair."""
    e1 = epr.request(1, demand)[0].qubit
    assert e1 is not None
    telegate_control_with(control, e1, cls)


def telegate_target(target: Qubit, epr: EPRSocket, cls: ClassicalSocket, demand: Demand) -> None:
    """Apply CNOT with a remote control onto `target` here, via one EPR pair."""
    e2 = epr.request(1, demand)[0].qubit
    assert e2 is not None
    telegate_target_with(target, e2, cls)


def telegate_control_with(control: Qubit, e1: Qubit, cls: ClassicalSocket) -> None:
    """Control half of a teleported CNOT over an EPR half already in hand.

    Split out from `telegate_control` so an application can supply a pair it
    obtained some other way — e.g. one it distilled (see `apps/distilled_gate.py`).
    """
    control.cnot(e1)  # entangle the control into the shared pair (cat-entangler)
    a = e1.measure(Basis.Z)
    cls.send(bytes([a]))  # the target needs this to correct its half
    b = cls.recv()[0]
    if b:
        control.apply(Gate.Z)  # Z correction from the target's X-basis measurement


def telegate_target_with(target: Qubit, e2: Qubit, cls: ClassicalSocket) -> None:
    """Target half of a teleported CNOT over an EPR half already in hand."""
    a = cls.recv()[0]
    if a:
        e2.apply(Gate.X)  # X correction from the control's Z-basis measurement
    e2.cnot(target)  # the shared pair now acts as the control on this target
    b = e2.measure(Basis.X)  # disentangle the pair (cat-disentangler)
    cls.send(bytes([b]))  # the control needs this for its Z correction
