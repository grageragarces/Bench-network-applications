"""qnetbench.apps — benchmark applications, each written once against the api.

The suite spans every demand-signature class: QKD (steady, fidelity-thresholded),
BQC (bursty, latency-coupled), distributed gate (deadline-critical), CHSH/DIQKD and
clock sync (correlation-quality-sensitive), anonymous transmission (multipartite),
and a family of DQC benchmarks whose demand is derived from real distributed
circuits (`qnetbench.circuits`).
"""

from __future__ import annotations

from qnetbench.api import Application
from qnetbench.apps.anonymous import AnonymousTransmission
from qnetbench.apps.bqc import BQC
from qnetbench.apps.chsh import CHSH
from qnetbench.apps.clock_sync import ClockSync
from qnetbench.apps.distributed_gate import DistributedGate
from qnetbench.apps.dqc import DQC
from qnetbench.apps.qkd import QKD
from qnetbench.circuits import ghz, qft, random_circuit

_APPS: tuple[Application, ...] = (
    QKD(),
    BQC(),
    DistributedGate(),
    CHSH(),
    ClockSync(),
    AnonymousTransmission(),
    # DQC benchmarks: demand derived from distributed circuits (GHZ, QFT, random).
    DQC(ghz(4)),
    DQC(qft(4)),
    DQC(random_circuit(4, depth=6, seed=0)),
)
_REGISTRY: dict[str, Application] = {app.name: app for app in _APPS}


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
    "DQC",
    "QKD",
    "AnonymousTransmission",
    "ClockSync",
    "DistributedGate",
    "available_apps",
    "get_app",
]
