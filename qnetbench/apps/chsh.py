"""CHSH / device-independent QKD test.

Demand signature: correlation-quality-sensitive (device-independent key
distribution). Each round consumes one pair; Alice and Bob each pick one of two
measurement angles and measure. The CHSH value S = E(0,0)+E(0,1)+E(1,0)−E(1,1)
is estimated from the correlations; S > 2 violates the classical bound and
S = 2√2 is the quantum (Tsirelson) maximum. Utility scales with how far S climbs
from the classical bound toward Tsirelson — which degrades directly with fidelity.
"""

from __future__ import annotations

import math

from qnetbench.api import AppOutcome, Basis, Demand, Gate, Host, Qubit, Role
from qnetbench.apps.util import cfg_int

_PEER = {"alice": "bob", "bob": "alice"}
# Optimal CHSH settings for |Φ+>: E(a,b) = cos(angle_a − angle_b).
_ANGLES = {"alice": (0.0, math.pi / 2), "bob": (math.pi / 4, -math.pi / 4)}
_TSIRELSON = 2 * math.sqrt(2)


def _measure_at(qubit: Qubit, angle: float) -> int:
    # Measure the observable cos(angle)·Z + sin(angle)·X: rotate by RY(−angle),
    # then measure Z. Returns the ±1 eigenvalue.
    qubit.apply(Gate.RY, -angle)
    return 1 - 2 * qubit.measure(Basis.Z)


class CHSH:
    name = "chsh"

    def __init__(self, rounds: int = 256, min_fidelity: float = 0.8) -> None:
        self.rounds = rounds
        self.min_fidelity = min_fidelity

    def roles(self) -> list[Role]:
        return ["alice", "bob"]

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        peer = _PEER[role]
        rounds = cfg_int(cfg, "rounds", self.rounds)
        epr = host.epr_socket(peer)
        cls = host.classical_socket(peer)
        demand = Demand(min_fidelity=self.min_fidelity, purpose="keep")
        angles = _ANGLES[role]

        settings: list[int] = []
        values: list[int] = []
        for _ in range(rounds):
            handle = epr.request(1, demand)[0]
            assert handle.qubit is not None
            setting = int(host.rng.integers(0, 2))
            value = _measure_at(handle.qubit, angles[setting])
            settings.append(setting)
            values.append(1 if value == 1 else 0)  # encode ±1 as bit for transport

        cls.send(bytes(settings) + bytes(values))
        their = cls.recv()
        their_settings = list(their[:rounds])
        their_values = list(their[rounds:])

        s_value = _chsh_value(role, settings, values, their_settings, their_values)
        utility = max(0.0, min(1.0, (s_value - 2.0) / (_TSIRELSON - 2.0)))
        return AppOutcome(
            role=role,
            success=s_value > 2.0,
            utility=utility,
            payload={"S": s_value},
        )


def _chsh_value(
    role: Role,
    my_settings: list[int],
    my_values: list[int],
    their_settings: list[int],
    their_values: list[int],
) -> float:
    # Pair outcomes by round; a/b index Alice/Bob settings regardless of role.
    sums = {(a, b): 0 for a in (0, 1) for b in (0, 1)}
    counts = {(a, b): 0 for a in (0, 1) for b in (0, 1)}
    for i in range(len(my_settings)):
        if role == "alice":
            a, b = my_settings[i], their_settings[i]
            va, vb = my_values[i], their_values[i]
        else:
            a, b = their_settings[i], my_settings[i]
            va, vb = their_values[i], my_values[i]
        prod = (1 - 2 * va) * (1 - 2 * vb)  # decode bits back to ±1
        sums[(a, b)] += prod
        counts[(a, b)] += 1

    def e(a: int, b: int) -> float:
        return sums[(a, b)] / counts[(a, b)] if counts[(a, b)] else 0.0

    return e(0, 0) + e(0, 1) + e(1, 0) - e(1, 1)
