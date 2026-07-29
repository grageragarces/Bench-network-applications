"""The single-qubit UBQC delegation gadget, shared by BQC and verified BQC.

The client remotely prepares |+_θ> on the server (measuring its half of a Φ+ pair in
the θ basis), sends the server a blinded measurement angle δ = -θ + (a+e+r)π, and
decodes the returned bit as s = b ⊕ r, which equals the secret input `e` noiselessly.
The server only ever sees a uniformly random angle, so the computation stays blind.
"""

from __future__ import annotations

import math

from qnetbench.api import Basis, ClassicalSocket, Gate, Host, Qubit

_QUARTER = math.pi / 4


def client_step(
    host: Host, qubit: Qubit, cls: ClassicalSocket, e: int | None = None
) -> tuple[int, int]:
    """Run one delegated measurement and return (decoded outcome s, input e used).

    `e` is the secret input bit; pass it for a trap (known answer), or leave it None
    to draw a random one. The random draw order (k, r, e) matches a plain UBQC step.
    """
    k = int(host.rng.integers(0, 8))  # secret θ = k·π/4
    r = int(host.rng.integers(0, 2))  # one-time pad bit
    if e is None:
        e = int(host.rng.integers(0, 2))
    qubit.apply(Gate.RZ, -k * _QUARTER)  # remote state prep: measure our half in the θ basis
    qubit.apply(Gate.H)
    a = qubit.measure(Basis.Z)
    host.record_measurement(Basis.Z, a)
    delta_index = (-k + 4 * ((a + e + r) % 2)) % 8  # blinded angle δ = -θ + (a+e+r)π
    cls.send(bytes([delta_index]))
    b = cls.recv()[0]
    return b ^ r, e  # s = b ⊕ r equals e noiselessly


def server_step(host: Host, qubit: Qubit, cls: ClassicalSocket) -> None:
    """Measure this qubit in the (blinded) basis the client asks for and return the bit."""
    delta_index = cls.recv()[0]
    qubit.apply(Gate.RZ, -delta_index * _QUARTER)
    qubit.apply(Gate.H)
    b = qubit.measure(Basis.Z)
    host.record_measurement(Basis.Z, b)
    cls.send(bytes([b]))
