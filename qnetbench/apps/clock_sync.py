"""Entanglement-based clock synchronization (distributed phase estimation).

Demand signature: sensing — steady and correlation-quality-sensitive. Bob's clock
carries an unknown phase offset φ. Each round consumes one pair: Alice measures her
half in X, Bob applies RZ(φ) (his clock) and measures in X. For |Φ+> the
correlation ⟨X_A X_B⟩ = cos(φ), so the agreement fraction estimates φ. Lower
delivered fidelity shrinks the correlation and biases the estimate — utility is the
estimation accuracy, so it degrades directly with correlation quality.
"""

from __future__ import annotations

import math

from qnetbench.api import AppOutcome, Basis, Demand, Gate, Host, Role
from qnetbench.apps.util import cfg_float, cfg_int

_PEER = {"alice": "bob", "bob": "alice"}


class ClockSync:
    name = "clock_sync"

    def __init__(
        self,
        rounds: int = 256,
        offset: float = math.pi / 3,
        min_fidelity: float = 0.8,
        tolerance: float = 0.1,
    ) -> None:
        self.rounds = rounds
        self.offset = offset  # true clock phase offset φ (radians, in [0, π])
        self.min_fidelity = min_fidelity
        self.tolerance = tolerance

    def roles(self) -> list[Role]:
        return ["alice", "bob"]

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        peer = _PEER[role]
        rounds = cfg_int(cfg, "rounds", self.rounds)
        phi = cfg_float(cfg, "offset", self.offset)
        epr = host.epr_socket(peer)
        cls = host.classical_socket(peer)
        demand = Demand(min_fidelity=self.min_fidelity, purpose="keep")

        bits: list[int] = []
        for _ in range(rounds):
            handle = epr.request(1, demand)[0]
            assert handle.qubit is not None
            if role == "bob":
                handle.qubit.apply(Gate.RZ, phi)  # Bob's local clock phase
            bits.append(handle.qubit.measure(Basis.X))

        cls.send(bytes(bits))
        their = list(cls.recv())
        agree = sum(1 for i in range(rounds) if bits[i] == their[i])
        p_agree = agree / rounds if rounds else 0.0
        correlation = 2 * p_agree - 1  # ⟨X_A X_B⟩ estimate ≈ cos(φ)
        phi_hat = math.acos(max(-1.0, min(1.0, correlation)))

        error = abs(phi_hat - phi)
        utility = max(0.0, 1.0 - error / math.pi)
        return AppOutcome(
            role=role,
            success=error < self.tolerance,
            utility=utility,
            payload={"phi": phi, "phi_hat": phi_hat, "error": error},
        )
