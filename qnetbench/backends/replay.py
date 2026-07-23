"""Shared machinery for *entanglement-supply* backends.

A supply backend lets an external simulator own the entanglement-generation
physics (delivery timing + fidelity) and replays that supply through the verified
reference engine, which runs the local quantum ops and classical protocol. Both
the SeQUeNCe and NetSquid backends are ~1-method subclasses of `ReplayBackend`:
they only implement `_make_supply`. This is the "adding a backend is easy"
property the suite's adoption goal depends on.
"""

from __future__ import annotations

from dataclasses import dataclass

from qnetbench.api.types import NodeId
from qnetbench.backends.reference.backend import ReferenceBackend
from qnetbench.policies.base import Policy
from qnetbench.topology import Topology


@dataclass(frozen=True)
class Supply:
    """A replayable entanglement supply between one pair of nodes.

    `inter_arrivals[i]` is the simulated-seconds gap before delivery i (the first
    is measured from the reservation/window start); `fidelities[i]` is that pair's
    delivered fidelity. `classical_latency` is the one-way classical delay.
    """

    inter_arrivals: list[float]
    fidelities: list[float]
    classical_latency: float

    def __len__(self) -> int:
        return len(self.fidelities)


@dataclass
class _Cursor:
    supply: Supply
    pos: int = 0


class ReplayBackend(ReferenceBackend):
    """A ReferenceBackend whose entanglement physics is replayed from a pre-generated
    per-edge `Supply`. Subclasses implement `_make_supply`."""

    def __init__(
        self,
        topology: Topology,
        seed: int,
        arbitration: str = "native",
        policy: Policy | None = None,
    ) -> None:
        super().__init__(topology, seed=seed, arbitration=arbitration, policy=policy)
        # Pre-generate every edge's supply eagerly, on the caller's (main) thread,
        # before any application role thread is spawned. Some simulators keep
        # process-global state that misbehaves when driven from worker threads.
        self._cursors: dict[frozenset[str], _Cursor] = {}
        for edge in topology.links:
            node, peer = sorted(edge)
            self._cursors[edge] = _Cursor(self._make_supply(node, peer))

    def _make_supply(self, node: NodeId, peer: NodeId) -> Supply:
        raise NotImplementedError

    def _cursor_for(self, node: NodeId, peer: NodeId) -> _Cursor:
        return self._cursors[frozenset((node, peer))]

    def _classical_latency(self, src: NodeId, dst: NodeId) -> float:
        return self._cursor_for(src, dst).supply.classical_latency

    def _sample_pairs(self, node: NodeId, peer: NodeId, pairs: int) -> tuple[float, list[float]]:
        cursor = self._cursor_for(node, peer)
        supply = cursor.supply
        end = cursor.pos + pairs
        if end > len(supply):
            raise RuntimeError(
                f"{self.backend_name} supply for {node!r}↔{peer!r} exhausted: needed "
                f"{end} pairs, the window produced {len(supply)}. Increase window_s."
            )
        latencies = supply.inter_arrivals[cursor.pos : end]
        fidelities = supply.fidelities[cursor.pos : end]
        cursor.pos = end
        return sum(latencies), list(fidelities)
