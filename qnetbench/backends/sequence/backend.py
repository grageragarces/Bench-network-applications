"""The SeQUeNCe backend (hybrid / entanglement-supply model).

SeQUeNCe owns the entanglement-generation physics: for each edge we run a
SeQUeNCe reservation and extract the delivered-pair stream (inter-arrival timing +
fidelity). The shared `ReplayBackend` then replays that supply through the
verified reference engine. Requires ``pip install qnetbench[sequence]``.
"""

from __future__ import annotations

import zlib

from qnetbench.api.types import NodeId
from qnetbench.backends.replay import ReplayBackend, Supply
from qnetbench.backends.sequence.supply import generate_supply
from qnetbench.policies.base import Policy
from qnetbench.topology import Topology

BACKEND_NAME = "sequence"


class SequenceBackend(ReplayBackend):
    backend_name = BACKEND_NAME

    def __init__(
        self,
        topology: Topology,
        seed: int,
        arbitration: str = "native",
        policy: Policy | None = None,
        window_s: float = 1.0,
        memo_size: int = 50,
    ) -> None:
        self.window_s = window_s
        self.memo_size = memo_size
        super().__init__(topology, seed=seed, arbitration=arbitration, policy=policy)

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
            memo_size=self.memo_size,
        )
