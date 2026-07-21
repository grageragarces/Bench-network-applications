"""qnetbench.api — the portable API shim.

This package and `qnetbench.trace` are the two frozen contracts of the suite.
Applications import only from here.
"""

from qnetbench.api.application import Application
from qnetbench.api.host import (
    ClassicalSocket,
    EntanglementHandle,
    EPRSocket,
    Host,
    Qubit,
)
from qnetbench.api.types import (
    AppOutcome,
    Basis,
    Demand,
    Duration,
    Gate,
    NodeId,
    Purpose,
    Role,
    SimTime,
    ViolationKind,
)

API_VERSION = "0.1.0"

__all__ = [
    "API_VERSION",
    "Application",
    "AppOutcome",
    "Basis",
    "ClassicalSocket",
    "Demand",
    "Duration",
    "EPRSocket",
    "EntanglementHandle",
    "Gate",
    "Host",
    "NodeId",
    "Purpose",
    "Qubit",
    "Role",
    "SimTime",
    "ViolationKind",
]
