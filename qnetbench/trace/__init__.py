"""qnetbench.trace — the versioned, machine-readable event schema and its I/O.

This package and `qnetbench.api` are the two frozen contracts of the suite.
"""

from qnetbench.trace.events import (
    SCHEMA_VERSION,
    AppOutcomeEvent,
    ClassicalMessage,
    ContractViolation,
    EntanglementDelivered,
    EntanglementRequested,
    Event,
    Measurement,
    QubitSent,
    RunHeader,
)
from qnetbench.trace.io import (
    TraceWriter,
    parse_event,
    read_trace,
    write_trace,
)

__all__ = [
    "SCHEMA_VERSION",
    "AppOutcomeEvent",
    "ClassicalMessage",
    "ContractViolation",
    "EntanglementDelivered",
    "EntanglementRequested",
    "Event",
    "Measurement",
    "QubitSent",
    "RunHeader",
    "TraceWriter",
    "parse_event",
    "read_trace",
    "write_trace",
]
