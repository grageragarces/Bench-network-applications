"""qnetbench.apps — benchmark applications.

The suite has two layers (the MQT Bench / SPEC model):

- a **core** of distinct protocols (`available_apps()`), spanning every demand class,
  that CI, the reference corpus, and the cross-backend equivalence suite all iterate;
- a **catalog** (`catalog_apps()`) of 50+ parameterized instances — mostly DQC over a
  family of distributed circuits at a range of sizes — resolvable and runnable on
  demand (`get_app`, `qnetbench run <name>`), but not all baked into CI.

Every application is one file against the api and inherits characterization, a
demand signature, and cross-backend equivalence for free.
"""

from __future__ import annotations

from qnetbench.api import Application
from qnetbench.apps.anonymous import AnonymousTransmission
from qnetbench.apps.b92 import B92
from qnetbench.apps.bb84 import BB84
from qnetbench.apps.bqc import BQC
from qnetbench.apps.byzantine import ByzantineAgreement
from qnetbench.apps.chsh import CHSH
from qnetbench.apps.clock_sync import ClockSync
from qnetbench.apps.conference_key import ConferenceKey
from qnetbench.apps.distillation import Distillation
from qnetbench.apps.distilled_gate import DistilledGate
from qnetbench.apps.distributed_gate import DistributedGate
from qnetbench.apps.dqc import DQC
from qnetbench.apps.heralded_teleport import HeraldedTeleport
from qnetbench.apps.leader_election import LeaderElection
from qnetbench.apps.multihop_qkd import MultihopQKD
from qnetbench.apps.oblivious_transfer import ObliviousTransfer
from qnetbench.apps.position_verification import PositionVerification
from qnetbench.apps.qkd import QKD
from qnetbench.apps.secret_sharing import SecretSharing
from qnetbench.apps.shared_randomness import SharedRandomness
from qnetbench.apps.six_state import SixState
from qnetbench.apps.swap import EntanglementSwap
from qnetbench.apps.teleport import Teleportation
from qnetbench.apps.threshold_secret_sharing import ThresholdSecretSharing
from qnetbench.apps.verified_bqc import VerifiedBQC
from qnetbench.circuits import ghz, graph_state, hea, iqp, qft, random_circuit

# --- core: distinct protocols, tested in CI + published in the corpus ----------

_CORE: tuple[Application, ...] = (
    QKD(),
    BB84(),
    B92(),
    SixState(),
    BQC(),
    DistributedGate(),
    Distillation(),
    DistilledGate(),
    HeraldedTeleport(),
    PositionVerification(),
    ObliviousTransfer(),
    CHSH(),
    ClockSync(),
    AnonymousTransmission(),
    ByzantineAgreement(),
    EntanglementSwap(),
    Teleportation(),
    MultihopQKD(),
    SharedRandomness(),
    SecretSharing(),
    ThresholdSecretSharing(),
    ConferenceKey(),
    VerifiedBQC(),
    LeaderElection(),
    DQC(ghz(4)),
    DQC(qft(4)),
    DQC(random_circuit(4, depth=6, seed=0)),
)
_CORE_REGISTRY: dict[str, Application] = {app.name: app for app in _CORE}

# --- catalog: the core plus parameterized DQC instances (run on demand) --------

_CIRCUIT_FAMILIES = {
    "ghz": ghz,
    "qft": qft,
    "random": random_circuit,
    "graph": graph_state,
    "iqp": iqp,
    "hea": hea,
}
_CATALOG_SIZES = (4, 5, 6, 7, 8, 9, 10)


def _build_catalog() -> dict[str, Application]:
    catalog = dict(_CORE_REGISTRY)
    for build in _CIRCUIT_FAMILIES.values():
        for n in _CATALOG_SIZES:
            app = DQC(build(n))
            catalog[app.name] = app
    return catalog


_CATALOG: dict[str, Application] = _build_catalog()


def get_app(name: str) -> Application:
    """Resolve any benchmark by name (core or catalog)."""
    try:
        return _CATALOG[name]
    except KeyError:
        raise KeyError(f"unknown app {name!r}; try `qnetbench list --all`") from None


def available_apps() -> list[str]:
    """The core protocol set (CI, corpus, cross-backend equivalence)."""
    return sorted(_CORE_REGISTRY)


def catalog_apps() -> list[str]:
    """The full catalog: core + parameterized instances (50+)."""
    return sorted(_CATALOG)


__all__ = [
    "B92",
    "BB84",
    "BQC",
    "CHSH",
    "DQC",
    "QKD",
    "AnonymousTransmission",
    "ByzantineAgreement",
    "ClockSync",
    "ConferenceKey",
    "Distillation",
    "DistilledGate",
    "DistributedGate",
    "EntanglementSwap",
    "HeraldedTeleport",
    "LeaderElection",
    "MultihopQKD",
    "ObliviousTransfer",
    "PositionVerification",
    "SecretSharing",
    "SharedRandomness",
    "SixState",
    "Teleportation",
    "ThresholdSecretSharing",
    "VerifiedBQC",
    "available_apps",
    "catalog_apps",
    "get_app",
]
