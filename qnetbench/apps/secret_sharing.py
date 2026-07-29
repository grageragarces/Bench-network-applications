"""(n, n) quantum secret sharing over a GHZ state (Hillery–Bužek–Berthiaume).

A dealer splits a secret bit among two players so that *both together* — but neither
alone — can recover it. The dealer fuses two Bell pairs into a 3-party GHZ, encodes
the secret by applying Z^s to its share, and everyone measures in X. The GHZ X-parity
gives d ⊕ p1 ⊕ p2 = s, so the dealer's public outcome plus the two players' bits
reconstruct s; each player alone holds only a uniformly random bit.

Demand signature: multipartite / GHZ-demand (like anonymous transmission, but a
threshold-reconstruction protocol rather than a broadcast). Utility is the fraction
of rounds the secret is reconstructed correctly, which degrades with GHZ fidelity.

Topology: a 3-node star with `dealer` at the hub, built by default.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Basis, Demand, Gate, Host, Role
from qnetbench.apps.util import cfg_int


class SecretSharing:
    name = "secret_sharing"

    def __init__(self, rounds: int = 64, min_fidelity: float = 0.8) -> None:
        self.rounds = rounds
        self.min_fidelity = min_fidelity

    def roles(self) -> list[Role]:
        return ["dealer", "player1", "player2"]  # dealer = hub (role[0])

    def _demand(self) -> Demand:
        return Demand(min_fidelity=self.min_fidelity, purpose="keep")

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        rounds = cfg_int(cfg, "rounds", self.rounds)
        if role == "dealer":
            return self._dealer(host, rounds)
        return self._player(host, role, rounds)

    def _dealer(self, host: Host, rounds: int) -> AppOutcome:
        epr_1, epr_2 = host.epr_socket("player1"), host.epr_socket("player2")
        cls_1, cls_2 = host.classical_socket("player1"), host.classical_socket("player2")
        correct = 0
        for _ in range(rounds):
            share = epr_1.request(1, self._demand())[0].qubit
            other = epr_2.request(1, self._demand())[0].qubit
            assert share is not None and other is not None
            # Fuse into a GHZ across (player1, dealer=share, player2); the X byproduct
            # from the Z-measurement doesn't affect an X-basis parity.
            share.cnot(other)
            other.measure(Basis.Z)
            cls_1.send(b"\x01")  # players measure only after the GHZ exists
            cls_2.send(b"\x01")
            secret = int(host.rng.integers(0, 2))
            if secret:
                share.apply(Gate.Z)  # encode the secret into the parity
            d = share.measure(Basis.X)
            p1, p2 = cls_1.recv()[0], cls_2.recv()[0]
            if (d ^ p1 ^ p2) == secret:  # reconstruction
                correct += 1
        for cls in (cls_1, cls_2):
            cls.send(bytes([correct >> 8, correct & 0xFF]))
        return _outcome("dealer", correct, rounds)

    def _player(self, host: Host, role: Role, rounds: int) -> AppOutcome:
        epr = host.epr_socket("dealer")
        cls = host.classical_socket("dealer")
        for _ in range(rounds):
            share = epr.request(1, self._demand())[0].qubit
            assert share is not None
            cls.recv()  # wait for the dealer's "GHZ ready"
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
