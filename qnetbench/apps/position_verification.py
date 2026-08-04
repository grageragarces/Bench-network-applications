"""Quantum position verification (distance bounding).

A verifier checks that a prover really is where it claims to be. The verifier shares
a pair with the prover, then challenges it with a basis chosen only at challenge
time; the prover must measure in that basis and answer correctly *and* fast enough
that no party further away could have produced the answer. Security rests on
no-cloning plus relativistic timing: a distant impostor cannot both learn the basis
and reply inside the light-travel bound.

Demand signature: the only application whose deadline is a *physical* quantity
rather than a tuning parameter. Everywhere else in the suite a deadline comes from a
circuit's layer budget or a chosen latency budget, and relaxing it merely degrades
performance; here the deadline is the round-trip propagation bound and relaxing it
destroys the security property outright. Late entanglement is not slow, it is
insecure — so a contract violation is a failed verification, not a slow one.

Utility is the fraction of rounds the prover answered both correctly and in time.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Basis, Demand, Host, Role
from qnetbench.apps.util import cfg_float, cfg_int


class PositionVerification:
    name = "position_verification"

    def __init__(
        self,
        rounds: int = 48,
        min_fidelity: float = 0.85,
        response_budget: float = 1e-2,
    ) -> None:
        self.rounds = rounds
        self.min_fidelity = min_fidelity
        # The round-trip light-travel bound for the claimed position. A pair that
        # arrives later than this cannot support a sound verification.
        self.response_budget = response_budget

    def roles(self) -> list[Role]:
        return ["verifier", "prover"]

    def _demand(self, host: Host, budget: float) -> Demand:
        return Demand(
            min_fidelity=self.min_fidelity,
            deadline=host.now() + budget,
            purpose="keep",
        )

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        rounds = cfg_int(cfg, "rounds", self.rounds)
        budget = cfg_float(cfg, "response_budget", self.response_budget)
        if role == "verifier":
            return self._verifier(host, rounds, budget)
        return self._prover(host, rounds, budget)

    def _verifier(self, host: Host, rounds: int, budget: float) -> AppOutcome:
        epr = host.epr_socket("prover")
        cls = host.classical_socket("prover")
        verified = 0
        late = 0
        wrong = 0
        for _ in range(rounds):
            handle = epr.request(1, self._demand(host, budget))[0]
            assert handle.qubit is not None
            # The challenge basis is chosen only now, so it cannot have been
            # anticipated by a party at another location.
            use_x = host.rng.random() < 0.5
            basis = Basis.X if use_x else Basis.Z
            cls.send(bytes([int(use_x)]))
            answer = cls.recv()[0]
            mine = handle.qubit.measure(basis)
            host.record_measurement(basis, mine)
            in_time = handle.ok  # the pair met its propagation-bound contract
            correct = answer == mine  # Φ+ is perfectly correlated in Z and in X
            if not in_time:
                late += 1
            if not correct:
                wrong += 1
            verified += int(in_time and correct)
        cls.send(bytes([verified >> 8, verified & 0xFF]))
        return _outcome("verifier", verified, rounds, late, wrong)

    def _prover(self, host: Host, rounds: int, budget: float) -> AppOutcome:
        epr = host.epr_socket("verifier")
        cls = host.classical_socket("verifier")
        for _ in range(rounds):
            handle = epr.request(1, self._demand(host, budget))[0]
            assert handle.qubit is not None
            use_x = cls.recv()[0]
            basis = Basis.X if use_x else Basis.Z
            bit = handle.qubit.measure(basis)
            host.record_measurement(basis, bit)
            cls.send(bytes([bit]))
        tally = cls.recv()
        verified = (tally[0] << 8) | tally[1]
        return _outcome("prover", verified, rounds, 0, 0)


def _outcome(role: Role, verified: int, rounds: int, late: int, wrong: int) -> AppOutcome:
    return AppOutcome(
        role=role,
        success=verified == rounds,
        utility=verified / rounds if rounds else 0.0,
        payload={"rounds": rounds, "verified": verified, "late": late, "wrong": wrong},
    )
