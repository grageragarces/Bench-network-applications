"""Network topology and the physical link model the backends draw from.

Phase 0 ships direct-link topologies only (no entanglement swapping); multi-hop
routing and swapping arrive with the SeQUeNCe backend.
"""

from __future__ import annotations

from dataclasses import dataclass

from qnetbench.api.types import NodeId


@dataclass(frozen=True)
class LinkModel:
    """Elementary-link entanglement generation parameters."""

    attempt_latency: float = 1e-3  # mean seconds to deliver one pair
    link_fidelity: float = 0.95  # mean delivered fidelity to Φ+
    fidelity_std: float = 0.01


@dataclass(frozen=True)
class Topology:
    name: str
    nodes: tuple[NodeId, ...]
    links: dict[frozenset[str], LinkModel]

    def link(self, a: NodeId, b: NodeId) -> LinkModel:
        try:
            return self.links[frozenset((a, b))]
        except KeyError:
            raise KeyError(f"no link between {a!r} and {b!r} in topology {self.name!r}") from None


def line2(
    a: NodeId = "alice",
    b: NodeId = "bob",
    *,
    link: LinkModel | None = None,
) -> Topology:
    """A single direct link between two nodes."""
    return Topology(name="line2", nodes=(a, b), links={frozenset((a, b)): link or LinkModel()})
