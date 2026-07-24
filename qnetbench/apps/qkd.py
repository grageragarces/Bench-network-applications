"""Entanglement-based QKD (E91 / BBM92).

Demand signature: steady, rate-hungry, fidelity-thresholded. Each round consumes
one fresh pair; matched-basis rounds are sifted; a public test subset estimates
QBER. Utility is the secure-key fraction; success requires QBER below threshold.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Basis, Demand, Host, Role
from qnetbench.apps.util import cfg_int

_PEER = {"alice": "bob", "bob": "alice"}


class QKD:
    name = "qkd"

    def __init__(
        self,
        rounds: int = 256,
        min_fidelity: float = 0.9,
        qber_threshold: float = 0.11,
    ) -> None:
        self.rounds = rounds
        self.min_fidelity = min_fidelity
        self.qber_threshold = qber_threshold

    def roles(self) -> list[Role]:
        return ["alice", "bob"]

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        peer = _PEER[role]
        rounds = cfg_int(cfg, "rounds", self.rounds)
        epr = host.epr_socket(peer)
        cls = host.classical_socket(peer)
        demand = Demand(min_fidelity=self.min_fidelity, purpose="keep")

        bases: list[int] = []  # 0 = Z, 1 = X
        bits: list[int] = []
        for _ in range(rounds):
            handle = epr.request(1, demand)[0]
            assert handle.qubit is not None
            use_x = host.rng.random() < 0.5
            basis = Basis.X if use_x else Basis.Z
            bit = handle.qubit.measure(basis)
            host.record_measurement(basis, bit)
            bases.append(1 if use_x else 0)
            bits.append(bit)

        # Basis reconciliation (public).
        cls.send(bytes(bases))
        their_bases = list(cls.recv())
        sifted = [i for i in range(rounds) if bases[i] == their_bases[i]]

        # Public test subset (every other sifted index) for QBER estimation.
        test = [i for k, i in enumerate(sifted) if k % 2 == 0]
        keep = [i for k, i in enumerate(sifted) if k % 2 == 1]
        cls.send(bytes(bits[i] for i in test))
        their_test = list(cls.recv())
        errors = sum(1 for j, i in enumerate(test) if bits[i] != their_test[j])
        qber = errors / len(test) if test else 0.0

        key = [bits[i] for i in keep]
        success = qber <= self.qber_threshold and len(key) > 0
        # Utility is the *secure* key rate: no secure key survives above the QBER
        # threshold, so utility collapses to 0 there (fidelity-thresholded signature).
        utility = min(len(key) / rounds, 1.0) if success and rounds else 0.0
        return AppOutcome(
            role=role,
            success=success,
            utility=utility,
            payload={"qber": qber, "key_len": len(key), "sifted": len(sifted)},
        )
