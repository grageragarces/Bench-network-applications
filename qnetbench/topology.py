"""Network topology and the physical link model the backends draw from.

Phase 0 ships direct-link topologies only (no entanglement swapping); multi-hop
routing and swapping arrive with the SeQUeNCe backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from qnetbench.api.types import NodeId

LinkNoise = Literal["depolarizing", "dephasing", "bit_flip"]


@dataclass(frozen=True)
class LinkModel:
    """Elementary-link entanglement generation parameters."""

    attempt_latency: float = 1e-3  # mean seconds to deliver one pair
    link_fidelity: float = 0.95  # mean delivered fidelity to Φ+
    fidelity_std: float = 0.01
    # The shape of a delivered pair's error at that fidelity, as a Bell-diagonal state:
    # "depolarizing" spreads it over the three other Bell states (a Werner pair),
    # "dephasing" puts it all on Φ-, and "bit_flip" all on Ψ+.
    noise: LinkNoise = "depolarizing"


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


def default_topology(roles: list[str], link: LinkModel | None = None) -> Topology:
    """The default topology for an application: a direct link for two roles, or a
    hub-and-spoke star (role[0] = hub) for multipartite applications."""
    if len(roles) == 2:
        return line2(roles[0], roles[1], link=link)
    return star(roles[0], list(roles[1:]), link=link)


def star(
    center: NodeId,
    leaves: list[NodeId],
    *,
    link: LinkModel | None = None,
) -> Topology:
    """A hub-and-spoke topology: `center` shares a direct link with each leaf.

    Multipartite applications (e.g. anonymous transmission) fuse the hub's
    bipartite pairs into a shared multipartite state.
    """
    return Topology(
        name=f"star{1 + len(leaves)}",
        nodes=(center, *leaves),
        links={frozenset((center, leaf)): link or LinkModel() for leaf in leaves},
    )
