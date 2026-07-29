"""The runtime surface an application sees. Applications program against these
Protocols and never import a backend or a simulator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np

from qnetbench.api.types import (
    Basis,
    Demand,
    Duration,
    Gate,
    NodeId,
    SimTime,
    ViolationKind,
)


@runtime_checkable
class Qubit(Protocol):
    """A local qubit handle. Physics lives in the backend; the app only sees ops."""

    def apply(self, gate: Gate, *params: float) -> None: ...
    def cnot(self, target: Qubit) -> None: ...
    def cz(self, target: Qubit) -> None: ...
    def measure(self, basis: Basis = Basis.Z) -> int: ...
    def free(self) -> None: ...


@dataclass
class EntanglementHandle:
    """The result of one delivered entangled pair, from the local host's side.

    For `purpose="keep"`, `qubit` is the live local half. For `purpose="measure"`,
    the backend measured on delivery and `outcome` holds the bit (`qubit` is None).
    `violations` is non-empty when the delivery broke its `Demand` contract; the
    handle is still returned so applications can decide how to degrade.
    """

    req_id: int
    fidelity: float
    latency: Duration
    pair_age: Duration
    qubit: Qubit | None = None
    outcome: int | None = None
    violations: list[ViolationKind] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


@runtime_checkable
class EPRSocket(Protocol):
    """Requests entanglement with one peer, under a demand contract."""

    def request(self, n: int, demand: Demand) -> list[EntanglementHandle]: ...


@runtime_checkable
class ClassicalSocket(Protocol):
    def send(self, msg: bytes) -> None: ...
    def recv(self) -> bytes: ...


@runtime_checkable
class Host(Protocol):
    """Everything an application role can do. Bound to one node for one run."""

    @property
    def node(self) -> NodeId: ...

    # Deterministic, per-(run, node) seeded RNG. Use this for all application
    # randomness so runs stay reproducible (never `random`/`numpy.random` globals).
    @property
    def rng(self) -> np.random.Generator: ...

    def epr_socket(self, peer: NodeId) -> EPRSocket: ...
    def classical_socket(self, peer: NodeId) -> ClassicalSocket: ...
    def qalloc(self) -> Qubit: ...

    # Single-qubit transmission over a quantum channel, for prepare-and-measure
    # protocols (e.g. BB84). `qsend` transfers a local qubit to `peer` (the channel
    # applies transmission noise); `qrecv` blocks for the next qubit from `peer`.
    def qsend(self, peer: NodeId, qubit: Qubit) -> None: ...
    def qrecv(self, peer: NodeId) -> Qubit: ...
    def now(self) -> SimTime: ...
    def sleep(self, duration: Duration) -> None: ...
    def record_measurement(self, basis: Basis, result: int) -> None: ...
