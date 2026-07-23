"""The NetSquid backend (hybrid / entanglement-supply model).

NetSquid owns the entanglement-generation physics (a QSource elementary link with
fibre delay + depolarising noise); the shared `ReplayBackend` replays that supply
through the verified reference engine. Requires ``pip install
qnetbench[netsquid]`` (NetSquid ships from https://pypi.netsquid.org).
"""

from __future__ import annotations

import zlib

from qnetbench.api.types import NodeId
from qnetbench.backends.netsquid.supply import generate_supply
from qnetbench.backends.replay import ReplayBackend, Supply
from qnetbench.policies.base import Policy
from qnetbench.topology import Topology

BACKEND_NAME = "netsquid"


class NetSquidBackend(ReplayBackend):
    backend_name = BACKEND_NAME

    def __init__(
        self,
        topology: Topology,
        seed: int,
        arbitration: str = "native",
        policy: Policy | None = None,
        window_s: float = 1.0,
    ) -> None:
        self.window_s = window_s
        super().__init__(topology, seed=seed, arbitration=arbitration, policy=policy)

    def _make_supply(self, node: NodeId, peer: NodeId) -> Supply:
        link = self.topology.link(node, peer)
        edge_seed = self.seed + (zlib.crc32("|".join(sorted((node, peer))).encode()) & 0xFFFF)
        return generate_supply(
            seed=edge_seed,
            window_s=self.window_s,
            link_fidelity=link.link_fidelity,
            classical_latency_s=link.attempt_latency,
        )
