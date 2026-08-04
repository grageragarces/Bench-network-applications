"""Entanglement distillation (BBPSSW/DEJMPS recurrence).

Two noisy pairs in, at most one better pair out. This is the only application in
the suite whose *output* is entanglement rather than a classical result, which
inverts its demand contract: it asks for many pairs at a low per-pair fidelity bar
and turns them into quality itself, where every other application asks the network
for quality directly.

Demand signature: rate-hungry with a deliberately *low* `min_fidelity` (raw pairs
are the input, so rejecting them defeats the purpose) and a tight
`staleness_tolerance` (the two pairs of a recurrence step must be co-temporal — the
first one waits in memory while the second is generated, and a decohered partner
destroys the step). This is the opposite corner of the demand space from the
fidelity-thresholded protocols, and the workload for which serving by fidelity
threshold is the wrong strategy.

Utility is the correlation quality of the distilled pairs; success additionally
requires that distillation actually *improved* on the raw pairs, measured in the
same run against a control sample.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Demand, Host, Role
from qnetbench.apps.purify import correlation_test, distill_step, test_basis
from qnetbench.apps.util import cfg_int

_SIGN = {"alice": 1, "bob": -1}  # DEJMPS rotates the two nodes in opposite senses
_PEER = {"alice": "bob", "bob": "alice"}


class Distillation:
    name = "distillation"

    def __init__(
        self,
        rounds: int = 48,
        control_rounds: int = 32,
        min_fidelity: float = 0.5,
        staleness_tolerance: float = 2e-3,
    ) -> None:
        self.rounds = rounds
        self.control_rounds = control_rounds
        self.min_fidelity = min_fidelity
        self.staleness_tolerance = staleness_tolerance

    def roles(self) -> list[Role]:
        return ["alice", "bob"]

    def _demand(self) -> Demand:
        # A low bar on purpose: raw pairs are the raw material, not the product.
        return Demand(
            min_fidelity=self.min_fidelity,
            staleness_tolerance=self.staleness_tolerance,
            purpose="keep",
        )

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        rounds = cfg_int(cfg, "rounds", self.rounds)
        control = cfg_int(cfg, "control_rounds", self.control_rounds)
        peer = _PEER[role]
        sign = _SIGN[role]
        epr = host.epr_socket(peer)
        cls = host.classical_socket(peer)

        # --- control sample: how good are the raw pairs? ----------------------
        raw_ok = 0
        for i in range(control):
            handle = epr.request(1, self._demand())[0]
            assert handle.qubit is not None
            raw_ok += int(correlation_test(handle.qubit, cls, test_basis(i)))

        # --- distillation: two raw pairs per attempt -------------------------
        kept = 0
        distilled_ok = 0
        for i in range(rounds):
            handles = epr.request(2, self._demand())
            keep, sacrifice = handles[0].qubit, handles[1].qubit
            assert keep is not None and sacrifice is not None
            if distill_step(keep, sacrifice, cls, sign=sign):
                kept += 1
                distilled_ok += int(correlation_test(keep, cls, test_basis(i)))
            else:
                keep.free()  # the step detected an error; the pair is spent

        raw_quality = raw_ok / control if control else 0.0
        distilled_quality = distilled_ok / kept if kept else 0.0
        # Yield is pairs out per pair in: the recurrence ceiling is 1/2, reached
        # only when every step is heralded successful.
        pair_yield = kept / (2 * rounds) if rounds else 0.0
        return AppOutcome(
            role=role,
            success=kept > 0 and distilled_quality >= raw_quality,
            utility=distilled_quality,
            payload={
                "kept": kept,
                "attempts": rounds,
                "yield": pair_yield,
                "raw_quality": raw_quality,
                "distilled_quality": distilled_quality,
            },
        )
