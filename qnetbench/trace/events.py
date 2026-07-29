"""The versioned trace event schema — the frozen wire contract.

A run is a stream of these, one JSON object per line. Metrics are computed from
traces, never inline, so any third-party tool can consume a run without importing
qnetbench. Bump `SCHEMA_VERSION` (semver) on any change to these models.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from qnetbench.api.types import Demand, ViolationKind

SCHEMA_VERSION = "0.2.0"  # 0.2.0 adds the qubit_sent event (single-qubit transmission)


class _Event(BaseModel):
    model_config = {"frozen": True}
    t: float  # simulated time of the event, seconds


class RunHeader(_Event):
    kind: Literal["run_header"] = "run_header"
    schema_version: str = SCHEMA_VERSION
    api_version: str
    app: str
    backend: str
    arbitration: str  # "native" or "policy:<name>"
    topology: str
    seed: int


class EntanglementRequested(_Event):
    kind: Literal["ent_requested"] = "ent_requested"
    req_id: int
    src: str
    dst: str
    n: int
    demand: Demand


class EntanglementDelivered(_Event):
    kind: Literal["ent_delivered"] = "ent_delivered"
    req_id: int
    actual_fidelity: float
    latency: float
    pair_age: float


class ContractViolation(_Event):
    kind: Literal["contract_violation"] = "contract_violation"
    req_id: int
    violation: ViolationKind


class ClassicalMessage(_Event):
    kind: Literal["classical_msg"] = "classical_msg"
    src: str
    dst: str
    n_bytes: int


class Measurement(_Event):
    kind: Literal["measurement"] = "measurement"
    node: str
    basis: str
    result: int


class QubitSent(_Event):
    """A single qubit transmitted over a quantum channel (prepare-and-measure
    protocols such as BB84), rather than a shared entangled pair."""

    kind: Literal["qubit_sent"] = "qubit_sent"
    src: str
    dst: str
    fidelity: float


class AppOutcomeEvent(_Event):
    kind: Literal["app_outcome"] = "app_outcome"
    role: str
    node: str
    success: bool
    utility: float
    payload: dict[str, object] = Field(default_factory=dict)


Event = Annotated[
    RunHeader
    | EntanglementRequested
    | EntanglementDelivered
    | ContractViolation
    | ClassicalMessage
    | Measurement
    | QubitSent
    | AppOutcomeEvent,
    Field(discriminator="kind"),
]
