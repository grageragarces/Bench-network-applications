"""Byzantine agreement — a GHZ-based detectable broadcast (simplified).

A general broadcasts a bit to two lieutenants; classical 3-party agreement with one
faulty party is impossible, but shared entanglement makes a faulty general's
*equivocation* detectable. Each round the general commits to its bit quantumly (Z^b
on its share of a 3-party GHZ, then measures in X), so g ⊕ l1 ⊕ l2 = b binds it. A
faulty general that claims b to one lieutenant and ¬b to the other fails that parity
check for one of them — the fault is detected rather than causing false agreement.

A round is *correct* if an honest general reaches consensus (both checks pass) or a
faulty general is caught (a check fails). Utility is the fraction of correct rounds,
which degrades with GHZ fidelity (noise flips the parity checks).

Demand signature: multipartite / GHZ-demand (3 parties), like secret sharing but with
consensus/fault-detection semantics.

Topology: a 3-node star with `general` at the hub, built by default.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Basis, Demand, Gate, Host, Role
from qnetbench.apps.util import cfg_int


class ByzantineAgreement:
    name = "byzantine_agreement"

    def __init__(
        self, rounds: int = 64, min_fidelity: float = 0.8, honest_prob: float = 0.7
    ) -> None:
        self.rounds = rounds
        self.min_fidelity = min_fidelity
        self.honest_prob = honest_prob

    def roles(self) -> list[Role]:
        return ["general", "lieutenant1", "lieutenant2"]  # general = hub (role[0])

    def _demand(self) -> Demand:
        return Demand(min_fidelity=self.min_fidelity, purpose="keep")

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        rounds = cfg_int(cfg, "rounds", self.rounds)
        if role == "general":
            return self._general(host, rounds)
        return self._lieutenant(host, role, rounds)

    def _general(self, host: Host, rounds: int) -> AppOutcome:
        epr1, epr2 = host.epr_socket("lieutenant1"), host.epr_socket("lieutenant2")
        cls1, cls2 = host.classical_socket("lieutenant1"), host.classical_socket("lieutenant2")
        correct = 0
        for _ in range(rounds):
            share = epr1.request(1, self._demand())[0].qubit
            other = epr2.request(1, self._demand())[0].qubit
            assert share is not None and other is not None
            share.cnot(other)  # fuse into a GHZ across (lt1, general=share, lt2)
            byproduct = other.measure(Basis.Z)  # X byproduct lands on lieutenant2

            b = int(host.rng.integers(0, 2))
            honest = host.rng.random() < self.honest_prob
            claim1, claim2 = b, (b if honest else 1 - b)  # a faulty general equivocates
            cls1.send(bytes([0, claim1]))  # lieutenant1: no correction
            cls2.send(bytes([byproduct, claim2]))
            if b:
                share.apply(Gate.Z)  # commit b: now g ⊕ l1 ⊕ l2 = b
            g = share.measure(Basis.X)

            l1, l2 = cls1.recv()[0], cls2.recv()[0]
            v1 = claim1 ^ g ^ l1 ^ l2  # 0 if lieutenant1 accepts its claim
            v2 = claim2 ^ g ^ l1 ^ l2
            if honest:
                correct += int(v1 == 0 and v2 == 0)  # consensus reached
            else:
                correct += int(v1 != 0 or v2 != 0)  # equivocation detected
        for cls in (cls1, cls2):
            cls.send(bytes([correct >> 8, correct & 0xFF]))
        return _outcome("general", correct, rounds)

    def _lieutenant(self, host: Host, role: Role, rounds: int) -> AppOutcome:
        epr = host.epr_socket("general")
        cls = host.classical_socket("general")
        for _ in range(rounds):
            share = epr.request(1, self._demand())[0].qubit
            assert share is not None
            correction, _claim = cls.recv()[:2]
            if correction:
                share.apply(Gate.X)
            cls.send(bytes([share.measure(Basis.X)]))
        tally = cls.recv()
        return _outcome(role, (tally[0] << 8) | tally[1], rounds)


def _outcome(role: Role, correct: int, rounds: int) -> AppOutcome:
    return AppOutcome(
        role=role,
        success=correct == rounds,
        utility=correct / rounds if rounds else 0.0,
        payload={"rounds": rounds, "correct": correct},
    )
