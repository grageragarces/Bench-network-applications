"""Fair leader election among five parties via shared GHZ randomness.

Five parties want to elect one leader uniformly at random, with all parties agreeing
on the outcome and no single party able to bias it. A coordinator fuses four
elementary pairs into a 5-party GHZ; measuring it in Z gives every party the *same*
uniformly-random bit (and the measurement is inherently random, so nobody controls
it). Several such bits form an index → the elected leader. An election is consistent
only if all five parties agree on every bit; utility is the fraction of consistent
elections, which degrades with GHZ fidelity.

Demand signature: the highest party count in the suite (5) — the coordinator carries
demand on four links per GHZ round, and a 5-party GHZ is extremely fidelity-fragile.

Topology: a 5-node star with `node0` (the coordinator) at the centre, built by default.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Basis, ClassicalSocket, Demand, EPRSocket, Gate, Host, Role
from qnetbench.apps.util import cfg_int

_N = 5
_CANDIDATES = tuple(f"node{i}" for i in range(_N))


class LeaderElection:
    name = "leader_election"

    def __init__(
        self, elections: int = 24, bits: int = 3, min_fidelity: float = 0.8
    ) -> None:
        self.elections = elections
        self.bits = bits  # GHZ rounds per election; leader = index mod 5
        self.min_fidelity = min_fidelity

    def roles(self) -> list[Role]:
        return list(_CANDIDATES)  # node0 = coordinator/hub (role[0])

    def _demand(self) -> Demand:
        return Demand(min_fidelity=self.min_fidelity, purpose="keep")

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        elections = cfg_int(cfg, "elections", self.elections)
        if role == "node0":
            return self._coordinator(host, elections)
        return self._candidate(host, role, elections)

    def _coordinator(self, host: Host, elections: int) -> AppOutcome:
        leaves = _CANDIDATES[1:]
        eprs = [host.epr_socket(leaf) for leaf in leaves]
        clss = [host.classical_socket(leaf) for leaf in leaves]
        consistent = 0
        for _ in range(elections):
            election_ok = True
            for _bit in range(self.bits):
                if not self._ghz_round_agrees(host, eprs, clss):
                    election_ok = False
            consistent += int(election_ok)
        for cls in clss:
            cls.send(bytes([consistent >> 8, consistent & 0xFF]))
        return _outcome("node0", consistent, elections)

    def _ghz_round_agrees(
        self, host: Host, eprs: list[EPRSocket], clss: list[ClassicalSocket]
    ) -> bool:
        shares = []
        for epr in eprs:
            qubit = epr.request(1, self._demand())[0].qubit
            assert qubit is not None
            shares.append(qubit)
        root, others = shares[0], shares[1:]
        for other in others:  # fuse the elementary pairs into a 5-party GHZ
            root.cnot(other)
        corrections = [0] + [q.measure(Basis.Z) for q in others]
        for cls, correction in zip(clss, corrections, strict=True):
            cls.send(bytes([correction]))
        key = root.measure(Basis.Z)  # this coordinator's share of the shared bit
        return all(cls.recv()[0] == key for cls in clss)

    def _candidate(self, host: Host, role: Role, elections: int) -> AppOutcome:
        epr = host.epr_socket("node0")
        cls = host.classical_socket("node0")
        for _ in range(elections * self.bits):
            qubit = epr.request(1, self._demand())[0].qubit
            assert qubit is not None
            if cls.recv()[0]:  # GHZ-fusion byproduct correction
                qubit.apply(Gate.X)
            cls.send(bytes([qubit.measure(Basis.Z)]))
        tally = cls.recv()
        return _outcome(role, (tally[0] << 8) | tally[1], elections)


def _outcome(role: Role, consistent: int, elections: int) -> AppOutcome:
    return AppOutcome(
        role=role,
        success=consistent == elections,
        utility=consistent / elections if elections else 0.0,
        payload={"elections": elections, "consistent": consistent},
    )
