"""Entanglement swapping over a three-node line: alice — repeater — bob.

Demand signature: multi-hop / relay. Alice and bob share no direct link. The
repeater holds one half of a pair with each of them and performs a Bell-state
measurement, swapping the two elementary links into one end-to-end pair (bob
applies a Pauli correction from the repeater's two classical bits). So every
end-to-end unit costs *two* elementary pairs — the routing/relay demand that
multi-hop schedulers and repeater-chain papers care about. Utility is the fraction
of rounds in which the swapped pair is correctly correlated, which degrades as the
two elementary pairs' fidelity drops (swapping compounds their noise).

Topology: a 3-node star with `repeater` at the hub (the line's middle node), built
by default. All classical traffic routes through the repeater.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Basis, Demand, Gate, Host, Role
from qnetbench.apps.util import cfg_int


class EntanglementSwap:
    name = "entanglement_swap"

    def __init__(self, rounds: int = 64, min_fidelity: float = 0.8) -> None:
        self.rounds = rounds
        self.min_fidelity = min_fidelity

    def roles(self) -> list[Role]:
        return ["repeater", "alice", "bob"]  # repeater = hub (role[0])

    def _demand(self) -> Demand:
        return Demand(min_fidelity=self.min_fidelity, purpose="keep")

    @staticmethod
    def _basis(round_index: int) -> Basis:
        # Alternate the (public) measurement basis so both Z and X correlations are
        # exercised; a swapped Φ+ is correlated in both.
        return Basis.X if round_index % 2 else Basis.Z

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        rounds = cfg_int(cfg, "rounds", self.rounds)
        if role == "repeater":
            return self._repeater(host, rounds)
        return self._endpoint(host, role, rounds)

    def _repeater(self, host: Host, rounds: int) -> AppOutcome:
        epr_a, epr_b = host.epr_socket("alice"), host.epr_socket("bob")
        cls_a, cls_b = host.classical_socket("alice"), host.classical_socket("bob")
        correlated = 0
        for _ in range(rounds):
            r1 = epr_a.request(1, self._demand())[0].qubit
            r2 = epr_b.request(1, self._demand())[0].qubit
            assert r1 is not None and r2 is not None
            # Bell-state measurement on the two inner halves swaps the entanglement.
            r1.cnot(r2)
            r1.apply(Gate.H)
            m1, m2 = r1.measure(Basis.Z), r2.measure(Basis.Z)
            cls_b.send(bytes([m1, m2]))  # bob's Pauli correction
            a, b = cls_a.recv()[0], cls_b.recv()[0]
            if a == b:  # swapped Φ+ is correlated in the shared basis
                correlated += 1
        for cls in (cls_a, cls_b):
            cls.send(bytes([correlated >> 8, correlated & 0xFF]))
        return self._outcome("repeater", correlated, rounds)

    def _endpoint(self, host: Host, role: Role, rounds: int) -> AppOutcome:
        epr = host.epr_socket("repeater")
        cls = host.classical_socket("repeater")
        for r in range(rounds):
            qubit = epr.request(1, self._demand())[0].qubit
            assert qubit is not None
            if role == "bob":  # apply the correction from the repeater's BSM
                m1, m2 = cls.recv()[:2]
                if m2:
                    qubit.apply(Gate.X)
                if m1:
                    qubit.apply(Gate.Z)
            outcome = qubit.measure(self._basis(r))
            cls.send(bytes([outcome]))
        tally = cls.recv()
        correlated = (tally[0] << 8) | tally[1]
        return self._outcome(role, correlated, rounds)

    def _outcome(self, role: Role, correlated: int, rounds: int) -> AppOutcome:
        return AppOutcome(
            role=role,
            success=correlated == rounds,
            utility=correlated / rounds if rounds else 0.0,
            payload={"rounds": rounds, "correlated": correlated},
        )
