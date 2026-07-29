"""Universal Blind Quantum Computation (UBQC), the minimal single-qubit delegated
pattern, chained `depth` times.

Demand signature: bursty, latency-coupled (each step is an entangle → measure →
send-angle → receive-outcome round trip), high-fidelity, classical-communication
heavy. The server only ever sees blinded measurement angles.

Each step delegates a single-qubit measurement whose ideal outcome equals a secret
input bit `e` the client chose. Remote state preparation from a Φ⁺ pair leaves the
server holding |+_{-θ+aπ}> (the Bell state conjugates the prepared angle); the
client sends the blinded angle δ = -θ + (a + e + r)π, the server measures and
returns b, and the client decodes s = b ⊕ r, which equals `e` noiselessly. The
server only ever sees a uniformly random δ, so the computation stays blind.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Demand, Host, Role
from qnetbench.apps.ubqc import client_step, server_step
from qnetbench.apps.util import cfg_int


class BQC:
    name = "bqc"

    def __init__(self, depth: int = 8, min_fidelity: float = 0.95, phi: float = 0.0) -> None:
        self.depth = depth
        self.min_fidelity = min_fidelity
        self.phi = phi

    def roles(self) -> list[Role]:
        return ["alice", "bob"]  # alice = client, bob = server

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        depth = cfg_int(cfg, "depth", self.depth)
        demand = Demand(min_fidelity=self.min_fidelity, latency_budget=0.05, purpose="keep")
        if role == "alice":
            return self._client(host, depth, demand)
        return self._server(host, depth, demand)

    def _client(self, host: Host, depth: int, demand: Demand) -> AppOutcome:
        epr = host.epr_socket("bob")
        cls = host.classical_socket("bob")
        correct = 0
        for _ in range(depth):
            qubit = epr.request(1, demand)[0].qubit
            assert qubit is not None
            s, e = client_step(host, qubit, cls)  # e is drawn randomly here
            if s == e:
                correct += 1
        return AppOutcome(
            role="alice",
            success=correct == depth,
            utility=correct / depth if depth else 0.0,
            payload={"depth": depth, "correct": correct},
        )

    def _server(self, host: Host, depth: int, demand: Demand) -> AppOutcome:
        epr = host.epr_socket("alice")
        cls = host.classical_socket("alice")
        for _ in range(depth):
            qubit = epr.request(1, demand)[0].qubit
            assert qubit is not None
            server_step(host, qubit, cls)
        # The server is blind: it reports participation, not the computation.
        return AppOutcome(role="bob", success=True, utility=1.0, payload={"depth": depth})
