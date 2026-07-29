"""Quantum state teleportation: Alice sends an unknown qubit state to Bob using one
shared EPR pair and two classical bits.

Demand signature: steady, latency-coupled (each teleport is entangle → Bell-measure
→ send two bits → correct), high-fidelity. Distinct from the distributed gate: this
moves a *state*, not a gate. Each round Alice prepares a secret state RY(kπ/4)|0>,
teleports it, and Bob reconstructs and un-rotates it; utility is the fraction of
rounds Bob recovers |0> (a correct teleport).
"""

from __future__ import annotations

import math

from qnetbench.api import AppOutcome, Basis, ClassicalSocket, Demand, Gate, Host, Role
from qnetbench.apps.util import cfg_int

_QUARTER = math.pi / 4


class Teleportation:
    name = "teleportation"

    def __init__(self, rounds: int = 64, min_fidelity: float = 0.85) -> None:
        self.rounds = rounds
        self.min_fidelity = min_fidelity

    def roles(self) -> list[Role]:
        return ["alice", "bob"]

    def _demand(self) -> Demand:
        return Demand(min_fidelity=self.min_fidelity, latency_budget=0.05, purpose="keep")

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        rounds = cfg_int(cfg, "rounds", self.rounds)
        if role == "alice":
            return self._sender(host, rounds)
        return self._receiver(host, rounds)

    def _sender(self, host: Host, rounds: int) -> AppOutcome:
        epr = host.epr_socket("bob")
        cls = host.classical_socket("bob")
        for _ in range(rounds):
            k = int(host.rng.integers(0, 8))  # secret state RY(kπ/4)|0>
            data = host.qalloc()
            data.apply(Gate.RY, k * _QUARTER)
            e_alice = epr.request(1, self._demand())[0].qubit
            assert e_alice is not None
            data.cnot(e_alice)  # Bell measurement of data with our EPR half
            data.apply(Gate.H)
            m1, m2 = data.measure(Basis.Z), e_alice.measure(Basis.Z)
            cls.send(bytes([m1, m2, k]))  # k travels for scoring, not reconstruction
        correct = _recv_count(cls)
        return _outcome("alice", correct, rounds)

    def _receiver(self, host: Host, rounds: int) -> AppOutcome:
        epr = host.epr_socket("alice")
        cls = host.classical_socket("alice")
        correct = 0
        for _ in range(rounds):
            e_bob = epr.request(1, self._demand())[0].qubit
            assert e_bob is not None
            m1, m2, k = cls.recv()[:3]
            if m2:
                e_bob.apply(Gate.X)  # Pauli corrections reconstruct |ψ> on Bob's qubit
            if m1:
                e_bob.apply(Gate.Z)
            e_bob.apply(Gate.RY, -k * _QUARTER)  # un-rotate; a correct teleport gives |0>
            if e_bob.measure(Basis.Z) == 0:
                correct += 1
        cls.send(bytes([correct >> 8, correct & 0xFF]))
        return _outcome("bob", correct, rounds)


def _recv_count(cls: ClassicalSocket) -> int:
    tally = cls.recv()
    return (tally[0] << 8) | tally[1]


def _outcome(role: Role, correct: int, rounds: int) -> AppOutcome:
    return AppOutcome(
        role=role,
        success=correct == rounds,
        utility=correct / rounds if rounds else 0.0,
        payload={"rounds": rounds, "correct": correct},
    )
