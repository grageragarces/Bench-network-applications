"""Conference key agreement over a 4-party GHZ state (multipartite QKD).

Four parties want one *shared* key bit — the N-party generalization of QKD. A hub
fuses three elementary pairs (one with each leaf) into a 4-party GHZ; every party
measures its share in Z, and a GHZ is perfectly Z-correlated, so all four obtain the
same bit. Utility is the fraction of rounds all four agree, which degrades with GHZ
fidelity.

Demand signature: multipartite with the highest party count in the suite (4), and
the hub carries demand on three links per key round — a genuinely different point in
the demand space from the 2- and 3-party protocols.

Topology: a 4-node star with `hub` at the centre, built by default.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Basis, Demand, Gate, Host, Role
from qnetbench.apps.util import cfg_int

_LEAVES = ("leaf1", "leaf2", "leaf3")


class ConferenceKey:
    name = "conference_key"

    def __init__(self, rounds: int = 64, min_fidelity: float = 0.8) -> None:
        self.rounds = rounds
        self.min_fidelity = min_fidelity

    def roles(self) -> list[Role]:
        return ["hub", *_LEAVES]  # hub = centre (role[0])

    def _demand(self) -> Demand:
        return Demand(min_fidelity=self.min_fidelity, purpose="keep")

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        rounds = cfg_int(cfg, "rounds", self.rounds)
        if role == "hub":
            return self._hub(host, rounds)
        return self._leaf(host, role, rounds)

    def _hub(self, host: Host, rounds: int) -> AppOutcome:
        eprs = [host.epr_socket(leaf) for leaf in _LEAVES]
        clss = [host.classical_socket(leaf) for leaf in _LEAVES]
        agree = 0
        for _ in range(rounds):
            shares = []
            for epr in eprs:
                qubit = epr.request(1, self._demand())[0].qubit
                assert qubit is not None
                shares.append(qubit)
            root, others = shares[0], shares[1:]
            # Fuse the elementary pairs into a 4-party GHZ across (leaf1, hub=root,
            # leaf2, leaf3). Measuring each fused qubit in Z leaves an X byproduct on
            # that leaf, which the leaf undoes from the classical bit below.
            for other in others:
                root.cnot(other)
            corrections = [0] + [q.measure(Basis.Z) for q in others]
            for cls, correction in zip(clss, corrections, strict=True):
                cls.send(bytes([correction]))  # 0 for leaf1 (just a "go"), byproduct for the rest
            key = root.measure(Basis.Z)
            if all(cls.recv()[0] == key for cls in clss):
                agree += 1
        for cls in clss:
            cls.send(bytes([agree >> 8, agree & 0xFF]))
        return _outcome("hub", agree, rounds)

    def _leaf(self, host: Host, role: Role, rounds: int) -> AppOutcome:
        epr = host.epr_socket("hub")
        cls = host.classical_socket("hub")
        for _ in range(rounds):
            share = epr.request(1, self._demand())[0].qubit
            assert share is not None
            if cls.recv()[0]:  # apply the GHZ-fusion byproduct correction
                share.apply(Gate.X)
            cls.send(bytes([share.measure(Basis.Z)]))
        tally = cls.recv()
        return _outcome(role, (tally[0] << 8) | tally[1], rounds)


def _outcome(role: Role, agree: int, rounds: int) -> AppOutcome:
    return AppOutcome(
        role=role,
        success=agree == rounds,
        utility=agree / rounds if rounds else 0.0,
        payload={"rounds": rounds, "agree": agree},
    )
