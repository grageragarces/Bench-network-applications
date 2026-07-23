"""qnetbench.apps — benchmark applications, each written once against the api.

Phase 0 ships the three most distinct demand signatures: QKD (steady,
fidelity-thresholded), BQC (bursty, latency-coupled), and a distributed gate
(deadline-critical). Applications #4–#6 (CHSH/DIQKD, clock sync, anonymous
transmission) land in a later phase.
"""

from __future__ import annotations

from qnetbench.api import Application
from qnetbench.apps.anonymous import AnonymousTransmission
from qnetbench.apps.bqc import BQC
from qnetbench.apps.chsh import CHSH
from qnetbench.apps.clock_sync import ClockSync
from qnetbench.apps.distributed_gate import DistributedGate
from qnetbench.apps.qkd import QKD

_REGISTRY: dict[str, Application] = {
    app.name: app
    for app in (QKD(), BQC(), DistributedGate(), CHSH(), ClockSync(), AnonymousTransmission())
}


def get_app(name: str) -> Application:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown app {name!r}; known: {sorted(_REGISTRY)}") from None


def available_apps() -> list[str]:
    return sorted(_REGISTRY)


__all__ = [
    "BQC",
    "CHSH",
    "QKD",
    "AnonymousTransmission",
    "ClockSync",
    "DistributedGate",
    "available_apps",
    "get_app",
]
