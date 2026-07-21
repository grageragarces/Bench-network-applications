"""The three published-style baseline policies used for the cross-policy
evaluation. Their ranking is expected to invert across workload classes."""

from __future__ import annotations

from qnetbench.policies.base import PendingRequest, Policy


class Fifo:
    """First-in, first-out: order by request time. The common default."""

    name = "fifo"

    def order(self, pending: list[PendingRequest], now: float) -> list[int]:
        return [p.req_id for p in sorted(pending, key=lambda p: (p.request_time, p.req_id))]


class FidelityFirst:
    """Serve the highest fidelity demand first — favours fidelity-thresholded
    workloads (QKD) at the expense of deadline-critical ones."""

    name = "fidelity_first"

    def order(self, pending: list[PendingRequest], now: float) -> list[int]:
        def key(p: PendingRequest) -> tuple[float, float, int]:
            return (-p.demand.min_fidelity, p.request_time, p.req_id)

        return [p.req_id for p in sorted(pending, key=key)]


class Edf:
    """Earliest-deadline-first — favours deadline-critical workloads (distributed
    gates) at the expense of steady rate-hungry ones."""

    name = "edf"

    def order(self, pending: list[PendingRequest], now: float) -> list[int]:
        def key(p: PendingRequest) -> tuple[float, float, int]:
            return (p.effective_deadline(), p.request_time, p.req_id)

        return [p.req_id for p in sorted(pending, key=key)]


_REGISTRY: dict[str, Policy] = {p.name: p for p in (Fifo(), FidelityFirst(), Edf())}


def get_policy(name: str) -> Policy:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown policy {name!r}; known: {sorted(_REGISTRY)}") from None


def available_policies() -> list[str]:
    return sorted(_REGISTRY)
