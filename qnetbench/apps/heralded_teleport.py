"""Session-based heralded teleportation (repeat-until-success).

A physical Bell-state measurement is heralded and probabilistic — a linear-optics
BSM succeeds at most half the time — so a teleport is not one pair but a geometric
number of them: attempt, listen for the herald, and on failure immediately consume
another pair. Between teleports the user is idle.

Demand signature: the suite's on/off duty cycle. Every other application requests
entanglement on a steady or circuit-paced cadence, which makes their demand
*sub*-Poissonian (Fano < 1, i.e. more regular than random arrivals). Here an idle
gap is followed by a burst of back-to-back retries, which is the super-Poissonian
(Fano > 1) regime that real user traffic occupies and that a scheduler's queueing
behaviour is most sensitive to.

Utility is the fraction of delivered teleports that reproduced the sent state;
the retry cost shows up in the demand signature rather than in the utility.
"""

from __future__ import annotations

import math

from qnetbench.api import AppOutcome, Basis, ClassicalSocket, Demand, Gate, Host, Role
from qnetbench.apps.util import cfg_float, cfg_int

_QUARTER = math.pi / 4
_MAX_GAP_US = 60000  # the idle gap travels as two bytes of microseconds


class HeraldedTeleport:
    name = "heralded_teleport"

    def __init__(
        self,
        sessions: int = 24,
        herald_prob: float = 0.4,
        max_attempts: int = 12,
        mean_idle: float = 0.02,
        min_fidelity: float = 0.85,
    ) -> None:
        self.sessions = sessions
        self.herald_prob = herald_prob
        self.max_attempts = max_attempts
        self.mean_idle = mean_idle
        self.min_fidelity = min_fidelity

    def roles(self) -> list[Role]:
        return ["alice", "bob"]

    def _demand(self) -> Demand:
        return Demand(min_fidelity=self.min_fidelity, purpose="keep")

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        sessions = cfg_int(cfg, "sessions", self.sessions)
        mean_idle = cfg_float(cfg, "mean_idle", self.mean_idle)
        if role == "alice":
            return self._sender(host, sessions, mean_idle)
        return self._receiver(host, sessions)

    def _sender(self, host: Host, sessions: int, mean_idle: float) -> AppOutcome:
        epr = host.epr_socket("bob")
        cls = host.classical_socket("bob")
        attempts_used = 0
        delivered = 0
        for _ in range(sessions):
            # Idle until this session has something to send. Alice picks the gap and
            # announces it so both nodes wake together.
            gap_us = min(int(host.rng.exponential(mean_idle * 1e6)), _MAX_GAP_US)
            cls.send(bytes([gap_us >> 8, gap_us & 0xFF]))
            host.sleep(gap_us / 1e6)

            for _attempt in range(self.max_attempts):
                attempts_used += 1
                pair = epr.request(1, self._demand())[0].qubit
                assert pair is not None
                heralded = host.rng.random() < self.herald_prob
                cls.send(bytes([int(heralded)]))
                if not heralded:
                    pair.free()  # the BSM failed; the pair is spent, try again
                    continue
                k = int(host.rng.integers(0, 8))  # the secret state RY(kπ/4)|0>
                data = host.qalloc()
                data.apply(Gate.RY, k * _QUARTER)
                data.cnot(pair)  # Bell measurement against our half
                data.apply(Gate.H)
                m1, m2 = data.measure(Basis.Z), pair.measure(Basis.Z)
                cls.send(bytes([m1, m2, k]))
                delivered += 1
                break

        correct = _recv_count(cls)
        return _outcome("alice", correct, delivered, attempts_used)

    def _receiver(self, host: Host, sessions: int) -> AppOutcome:
        epr = host.epr_socket("alice")
        cls = host.classical_socket("alice")
        attempts_used = 0
        delivered = 0
        correct = 0
        for _ in range(sessions):
            gap = cls.recv()
            host.sleep(((gap[0] << 8) | gap[1]) / 1e6)

            for _attempt in range(self.max_attempts):
                attempts_used += 1
                pair = epr.request(1, self._demand())[0].qubit
                assert pair is not None
                if not cls.recv()[0]:  # herald: the sender's BSM failed
                    pair.free()
                    continue
                m1, m2, k = cls.recv()[:3]
                if m2:
                    pair.apply(Gate.X)  # Pauli corrections reconstruct |ψ>
                if m1:
                    pair.apply(Gate.Z)
                pair.apply(Gate.RY, -k * _QUARTER)  # un-rotate: a good teleport gives |0>
                delivered += 1
                correct += int(pair.measure(Basis.Z) == 0)
                break

        cls.send(bytes([correct >> 8, correct & 0xFF]))
        return _outcome("bob", correct, delivered, attempts_used)


def _recv_count(cls: ClassicalSocket) -> int:
    tally = cls.recv()
    return (tally[0] << 8) | tally[1]


def _outcome(role: Role, correct: int, delivered: int, attempts: int) -> AppOutcome:
    return AppOutcome(
        role=role,
        success=delivered > 0 and correct == delivered,
        utility=correct / delivered if delivered else 0.0,
        payload={
            "delivered": delivered,
            "correct": correct,
            "attempts": attempts,
            "pairs_per_teleport": attempts / delivered if delivered else 0.0,
        },
    )
