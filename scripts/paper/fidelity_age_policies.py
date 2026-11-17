"""The schedulers of Ercetin and Gedik (arXiv:2602.09562), written outside the package.

Everything here goes through `register_policy` and the seam's optional hooks, so the line count
of this file is itself evidence of how easily a published scheduler can be added.

Choices the preprint leaves open, stated so they can be challenged:

- U is never defined. The preprint says beta -> 0 yields TP-MAX, whose objective is the estimated
  success probability, so U is taken as that probability.
- On one link every flow has the same success probability, except that a pair below a flow's
  F_min is not usable, so U is 1 if the link fidelity clears F_min and 0 otherwise.
- Eqs. (15) and (16) as printed fall as age grows, so they favour recently served flows. The text
  says the opposite: these policies "rejuvenate stale flows" and large beta "approaches equal-age
  service". `as_printed=True` is Eq. (16) exactly, U / (1 + beta A). `as_printed=False` is the
  stated intent, U (1 + beta A).
- A delivery is usable if its fidelity clears F_min, as in the preprint's Y_t.
- FA-THR(tau) as printed serves nothing when no flow is older than tau. Here it falls back to the
  highest U, because an idle link would otherwise be an artefact of a threshold on a single link.
"""

from __future__ import annotations

from qnetbench.policies.base import PendingRequest
from qnetbench.policies.builtin import _REGISTRY, register_policy

LINK_FIDELITY = 0.99


def _utility(request: PendingRequest, link_fidelity: float) -> float:
    return 1.0 if link_fidelity >= request.demand.min_fidelity else 0.0


class _Aged:
    """Keeps each tenant's time of last usable delivery."""

    def __init__(self, link_fidelity: float = LINK_FIDELITY) -> None:
        self.link_fidelity = link_fidelity
        self._last: dict[str, float] = {}

    def reset(self) -> None:
        self._last = {}

    def on_delivery(self, request: PendingRequest, fidelity: float, at: float) -> None:
        if fidelity >= request.demand.min_fidelity:
            self._last[request.tenant] = at

    def age(self, request: PendingRequest, now: float) -> float:
        return now - self._last.get(request.tenant, 0.0)


class FaIndex(_Aged):
    """FA-INDEX, Eq. (16). A is in seconds here and in slots in the preprint. With U equal across
    flows the order does not depend on beta, so the unit only matters when U differs."""

    def __init__(self, beta: float, *, as_printed: bool, slot: float = 1.0 / 160) -> None:
        super().__init__()
        self.beta = beta
        self.as_printed = as_printed
        self.slot = slot
        self.name = f"fa_index_{'printed' if as_printed else 'intended'}"

    def order(self, pending: list[PendingRequest], now: float) -> list[int]:
        def index(p: PendingRequest) -> float:
            utility = _utility(p, self.link_fidelity)
            weight = 1.0 + self.beta * self.age(p, now) / self.slot
            return utility / weight if self.as_printed else utility * weight

        ranked = sorted(pending, key=lambda p: (-index(p), p.request_time, p.req_id))
        return [p.req_id for p in ranked]


class FaThreshold(_Aged):
    """FA-THR(tau): flows older than tau first, each group by highest U."""

    def __init__(self, tau_slots: float = 5.0, slot: float = 1.0 / 160) -> None:
        super().__init__()
        self.tau = tau_slots * slot
        self.name = "fa_thr"

    def order(self, pending: list[PendingRequest], now: float) -> list[int]:
        def key(p: PendingRequest) -> tuple[bool, float, float, int]:
            stale = self.age(p, now) > self.tau
            return (not stale, -_utility(p, self.link_fidelity), p.request_time, p.req_id)

        return [p.req_id for p in sorted(pending, key=key)]


class TpMax:
    """TP-MAX: the highest estimated success probability. On one link that is a tie, so it
    falls to arrival order."""

    name = "tp_max"

    def order(self, pending: list[PendingRequest], now: float) -> list[int]:
        def key(p: PendingRequest) -> tuple[float, float, int]:
            return (-_utility(p, LINK_FIDELITY), p.request_time, p.req_id)

        return [p.req_id for p in sorted(pending, key=key)]


class FidMax(TpMax):
    """FID-MAX: the highest expected fidelity, which one link gives every flow equally."""

    name = "fid_max"


def register_all(*, slot: float = 1.0 / 160) -> list[str]:
    policies = [
        TpMax(),
        FidMax(),
        FaIndex(0.1, as_printed=True, slot=slot),
        FaIndex(0.1, as_printed=False, slot=slot),
        FaThreshold(5.0, slot=slot),
    ]
    return [register_policy(p, replace=p.name in _REGISTRY) for p in policies]
