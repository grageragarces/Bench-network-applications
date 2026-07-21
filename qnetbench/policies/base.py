"""The arbitration seam.

A `Policy` orders contending entanglement requests. It is only consulted in
`policy:<name>` arbitration mode; in `native` mode the backend uses its own
default (FIFO on the reference backend, the simulator's own layer on
SeQUeNCe/NetSquid). Routing is a single hop in Phase 0's topologies and is added
to this Protocol when multi-hop swapping lands.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from qnetbench.api.types import Demand, NodeId, SimTime


@dataclass(frozen=True)
class PendingRequest:
    req_id: int
    src: NodeId
    dst: NodeId
    n: int
    demand: Demand
    request_time: SimTime

    def effective_deadline(self) -> float:
        """Absolute time this request must be served by, or +inf if unbounded."""
        if self.demand.deadline is not None:
            return self.demand.deadline
        if self.demand.latency_budget is not None:
            return self.request_time + self.demand.latency_budget
        return float("inf")


@runtime_checkable
class Policy(Protocol):
    name: str

    def order(self, pending: list[PendingRequest], now: SimTime) -> list[int]:
        """Return the req_ids of `pending`, most-urgent first."""
        ...
