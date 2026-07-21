"""The SeQUeNCe backend (hybrid / entanglement-supply model).

SeQUeNCe owns the entanglement-generation physics: for each edge we run a
SeQUeNCe reservation and extract the delivered-pair stream (inter-arrival timing +
fidelity). qnetbench's verified execution engine then replays that supply and runs
the local quantum operations and the classical protocol — so applications behave
identically across backends, differing only in how entanglement is supplied.

This reuses ``ReferenceBackend`` wholesale, overriding only the two physics hooks
(``_sample_pairs`` and ``_classical_latency``). Requires ``pip install
qnetbench[sequence]``.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

from qnetbench.api.types import NodeId
from qnetbench.backends.reference.backend import ReferenceBackend
from qnetbench.backends.sequence.supply import Supply, generate_supply
from qnetbench.policies.base import Policy
from qnetbench.topology import Topology

BACKEND_NAME = "sequence"


@dataclass
class _Cursor:
    supply: Supply
    pos: int = 0


class SequenceBackend(ReferenceBackend):
    backend_name = BACKEND_NAME

    def __init__(
        self,
        topology: Topology,
        seed: int,
        arbitration: str = "native",
        policy: Policy | None = None,
        window_s: float = 1.0,
    ) -> None:
        super().__init__(topology, seed=seed, arbitration=arbitration, policy=policy)
        self.window_s = window_s
        # Pre-generate every edge's supply eagerly here, on the caller's (main)
        # thread. SeQUeNCe keeps process-global state that misbehaves when driven
        # from the cooperative engine's worker threads, so supply generation must
        # happen before any application role thread is spawned.
        self._cursors: dict[frozenset[str], _Cursor] = {}
        for edge in topology.links:
            node, peer = sorted(edge)
            self._cursors[edge] = _Cursor(self._make_supply(node, peer))

    def _make_supply(self, node: NodeId, peer: NodeId) -> Supply:
        link = self.topology.link(node, peer)
        # Stable per-edge seed so runs are reproducible across processes
        # (hash() is salted per-process; crc32 is not).
        edge_seed = self.seed + (zlib.crc32("|".join(sorted((node, peer))).encode()) & 0xFFFF)
        return generate_supply(
            seed=edge_seed,
            window_s=self.window_s,
            link_fidelity=link.link_fidelity,
            classical_latency_s=link.attempt_latency,
            target_fidelity=max(0.0, link.link_fidelity - 1e-6),
        )

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
                f"SeQUeNCe supply for {node!r}↔{peer!r} exhausted: needed {end} pairs, "
                f"the {self.window_s}s reservation produced {len(supply)}. Increase "
                "window_s on the SequenceBackend."
            )
        latencies = supply.inter_arrivals[cursor.pos : end]
        fidelities = supply.fidelities[cursor.pos : end]
        cursor.pos = end
        return sum(latencies), list(fidelities)
