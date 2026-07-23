"""Anonymous transmission via a shared GHZ state (multipartite broadcast).

Demand signature: multipartite, GHZ-demand. The hub (`charlie`) fuses two
bipartite pairs — one with each leaf — into a three-party GHZ state, then the
parties run a GHZ-parity anonymous broadcast: each round a designated sender
encodes a bit by applying Z to their qubit, everyone measures in X, and the parity
of the outcomes reveals the bit without the transcript identifying the sender.
Utility is the fraction of rounds whose bit is recovered correctly; it degrades
with GHZ fidelity, which is set by the two elementary pairs.

Topology: a 3-node star with `charlie` at the hub (built by default).
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Basis, Demand, Gate, Host, Role
from qnetbench.apps.util import cfg_int

# Public per-round sender schedule: sender = round % 3 over this party order.
_PARTY_INDEX = {"alice": 0, "bob": 1, "charlie": 2}


class AnonymousTransmission:
    name = "anonymous_transmission"

    def __init__(self, rounds: int = 64, min_fidelity: float = 0.8) -> None:
        self.rounds = rounds
        self.min_fidelity = min_fidelity

    def roles(self) -> list[Role]:
        return ["charlie", "alice", "bob"]  # charlie = hub (role[0])

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        rounds = cfg_int(cfg, "rounds", self.rounds)
        demand = Demand(min_fidelity=self.min_fidelity, purpose="keep")
        if role == "charlie":
            return self._hub(host, rounds, demand)
        return self._leaf(host, role, rounds, demand)

    def _hub(self, host: Host, rounds: int, demand: Demand) -> AppOutcome:
        epr_a, epr_b = host.epr_socket("alice"), host.epr_socket("bob")
        cls_a, cls_b = host.classical_socket("alice"), host.classical_socket("bob")
        correct = 0
        for r in range(rounds):
            ca = epr_a.request(1, demand)[0].qubit
            cb = epr_b.request(1, demand)[0].qubit
            assert ca is not None and cb is not None
            # Fuse the two pairs into a GHZ across (alice, charlie=ca, bob). The X
            # byproduct from the Z-measurement doesn't affect an X-basis parity.
            ca.cnot(cb)
            cb.measure(Basis.Z)
            cls_a.send(b"\x01")  # "GHZ ready" — leaves measure only after fusion
            cls_b.send(b"\x01")

            m_charlie = 0
            if r % 3 == _PARTY_INDEX["charlie"]:
                m_charlie = int(host.rng.integers(0, 2))
                if m_charlie:
                    ca.apply(Gate.Z)
            c_bit = ca.measure(Basis.X)

            a_bit, a_m = cls_a.recv()
            b_bit, b_m = cls_b.recv()
            parity = a_bit ^ b_bit ^ c_bit
            sender = r % 3
            true_m = a_m if sender == 0 else (b_m if sender == 1 else m_charlie)
            if parity == true_m:
                correct += 1

        cls_a.send(bytes([correct]))
        cls_b.send(bytes([correct]))
        utility = correct / rounds if rounds else 0.0
        return AppOutcome(
            role="charlie",
            success=correct == rounds,
            utility=utility,
            payload={"rounds": rounds, "correct": correct},
        )

    def _leaf(self, host: Host, role: Role, rounds: int, demand: Demand) -> AppOutcome:
        epr = host.epr_socket("charlie")
        cls = host.classical_socket("charlie")
        idx = _PARTY_INDEX[role]
        for r in range(rounds):
            qubit = epr.request(1, demand)[0].qubit
            assert qubit is not None
            cls.recv()  # wait for the hub's "GHZ ready" before measuring
            m = 0
            if r % 3 == idx:  # this party is the anonymous sender this round
                m = int(host.rng.integers(0, 2))
                if m:
                    qubit.apply(Gate.Z)
            x_bit = qubit.measure(Basis.X)
            cls.send(bytes([x_bit, m]))

        correct = cls.recv()[0]
        utility = correct / rounds if rounds else 0.0
        return AppOutcome(
            role=role,
            success=correct == rounds,
            utility=utility,
            payload={"rounds": rounds, "correct": correct},
        )
