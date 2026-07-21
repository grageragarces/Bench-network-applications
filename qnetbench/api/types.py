"""Core value types for the portable API shim.

This module has no dependencies inside qnetbench, so both `qnetbench.api` and
`qnetbench.trace` can build on it without a cycle.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, TypeAlias

from pydantic import BaseModel, Field

# --- primitive aliases -------------------------------------------------------

NodeId: TypeAlias = str
Role: TypeAlias = str
SimTime: TypeAlias = float  # absolute simulated time, seconds
Duration: TypeAlias = float  # elapsed simulated time, seconds


class Basis(str, Enum):
    """Measurement basis for a local qubit. Arbitrary-angle measurements are
    expressed by rotating the qubit (RY/RZ) and then measuring in Z."""

    Z = "Z"
    X = "X"
    Y = "Y"


class Gate(str, Enum):
    """Single-qubit gates. Two-qubit gates are methods on `Qubit` (cnot/cz)."""

    I = "I"  # noqa: E741 — the identity gate is conventionally named I
    X = "X"
    Y = "Y"
    Z = "Z"
    H = "H"
    S = "S"
    T = "T"
    RX = "RX"
    RY = "RY"
    RZ = "RZ"


Purpose = Literal["keep", "measure"]
ViolationKind = Literal["fidelity", "deadline", "staleness", "dropped"]


class Demand(BaseModel):
    """The contract attached to a request for entanglement.

    This is what makes the suite discriminative: schedulers read it, the trace
    records requested-vs-delivered against it, and the characterizer mines its
    distribution across an application's run.
    """

    model_config = {"frozen": True}

    min_fidelity: float = Field(0.0, ge=0.0, le=1.0)
    latency_budget: Duration | None = None  # soft deadline, measured from request
    deadline: SimTime | None = None  # hard absolute deadline (distributed gates)
    staleness_tolerance: Duration | None = None  # max usable age of a pre-made pair
    priority: float = 1.0
    purpose: Purpose = "keep"


class AppOutcome(BaseModel):
    """What an application role reports when it finishes.

    `utility` is application-defined in [0, 1] and is the quantity the
    staleness/fidelity curves are plotted against.
    """

    role: Role
    success: bool
    utility: float = Field(ge=0.0, le=1.0)
    payload: dict[str, object] = Field(default_factory=dict)
