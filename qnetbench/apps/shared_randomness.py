"""Shared randomness from measured entangled pairs.

The only application that uses `purpose="measure"`: instead of keeping the local
qubit, each side asks the backend to measure its half on delivery and return the
bit. A Φ+ pair measured in Z on both sides yields the *same* random bit, so alice
and bob harvest correlated shared randomness. They reveal a test subset to check the
correlation; the rest is their shared random string.

Demand signature: steady and rate-hungry like QKD, but the demand *shape* differs —
`purpose="measure"` means no local qubit is ever handed to the application, so the
backend measures immediately (no memory hold, no local gates).
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Demand, Host, Role
from qnetbench.apps.util import cfg_int

_PEER = {"alice": "bob", "bob": "alice"}


class SharedRandomness:
    name = "shared_randomness"

    def __init__(
        self, rounds: int = 128, min_fidelity: float = 0.8, agree_threshold: float = 0.9
    ) -> None:
        self.rounds = rounds
        self.min_fidelity = min_fidelity
        self.agree_threshold = agree_threshold

    def roles(self) -> list[Role]:
        return ["alice", "bob"]

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        peer = _PEER[role]
        rounds = cfg_int(cfg, "rounds", self.rounds)
        epr = host.epr_socket(peer)
        cls = host.classical_socket(peer)
        demand = Demand(min_fidelity=self.min_fidelity, purpose="measure")

        bits: list[int] = []
        for _ in range(rounds):
            handle = epr.request(1, demand)[0]
            assert handle.outcome is not None  # measured on delivery (purpose="measure")
            bits.append(handle.outcome)

        # Reveal a test subset (public rule) to check the shared bits agree.
        test = [i for i in range(rounds) if i % 2 == 0]
        keep = [i for i in range(rounds) if i % 2 == 1]
        cls.send(bytes(bits[i] for i in test))
        their_test = list(cls.recv())
        agree = sum(1 for j, i in enumerate(test) if bits[i] == their_test[j])
        agreement = agree / len(test) if test else 0.0

        return AppOutcome(
            role=role,
            success=agreement >= self.agree_threshold,
            utility=agreement,
            payload={"agreement": agreement, "shared_bits": len(keep)},
        )
