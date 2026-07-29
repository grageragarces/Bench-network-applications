"""Verified blind quantum computation (trap-based).

Like BQC, the client delegates single-qubit measurements to a blind server — but it
secretly interleaves *trap* rounds whose answer it already knows. If any trap comes
back wrong (a corrupt or noisy server), the client rejects the whole computation. So
unlike plain BQC (which just reports a result), verified BQC is an accept/reject
*verification*: utility is the trap pass rate — the client's confidence — and success
means every trap passed.

Demand signature: like BQC (bursty, latency-coupled, high-fidelity, classical-heavy),
with extra rounds spent on traps — the price of verification.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Demand, Host, Role
from qnetbench.apps.ubqc import client_step, server_step
from qnetbench.apps.util import cfg_int


class VerifiedBQC:
    name = "verified_bqc"

    def __init__(
        self, rounds: int = 16, min_fidelity: float = 0.95, trap_ratio: float = 0.5
    ) -> None:
        self.rounds = rounds
        self.min_fidelity = min_fidelity
        self.trap_ratio = trap_ratio

    def roles(self) -> list[Role]:
        return ["alice", "bob"]  # alice = client/verifier, bob = blind server

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        rounds = cfg_int(cfg, "rounds", self.rounds)
        demand = Demand(min_fidelity=self.min_fidelity, latency_budget=0.05, purpose="keep")
        if role == "alice":
            return self._client(host, rounds, demand)
        return self._server(host, rounds, demand)

    def _client(self, host: Host, rounds: int, demand: Demand) -> AppOutcome:
        epr = host.epr_socket("bob")
        cls = host.classical_socket("bob")
        traps = 0
        traps_passed = 0
        computation = 0
        for _ in range(rounds):
            qubit = epr.request(1, demand)[0].qubit
            assert qubit is not None
            is_trap = host.rng.random() < self.trap_ratio  # the server can't tell which
            s, e = client_step(host, qubit, cls)
            if is_trap:  # a round whose answer the client already knows
                traps += 1
                if s == e:
                    traps_passed += 1
            else:  # a real (blind) computation step; its result is used, not checked
                computation += 1
        # Accept the computation only if every trap passed; utility is the pass rate.
        return AppOutcome(
            role="alice",
            success=traps_passed == traps,
            utility=traps_passed / traps if traps else 1.0,
            payload={"traps": traps, "traps_passed": traps_passed, "computation": computation},
        )

    def _server(self, host: Host, rounds: int, demand: Demand) -> AppOutcome:
        epr = host.epr_socket("alice")
        cls = host.classical_socket("alice")
        for _ in range(rounds):
            qubit = epr.request(1, demand)[0].qubit
            assert qubit is not None
            server_step(host, qubit, cls)  # blind: it cannot distinguish traps
        return AppOutcome(role="bob", success=True, utility=1.0, payload={"rounds": rounds})
