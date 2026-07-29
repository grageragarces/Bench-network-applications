"""Single-trace demand-signature extraction.

The dimensions here are read directly from one run's trace (no parameter sweep):
burstiness of entanglement requests, classical-communication coupling,
deadline-criticality, staleness-intolerance, and multipartiteness. The
fidelity/staleness *curves* (which need sweeps) live in `curves.py`.
"""

from __future__ import annotations

import statistics

from pydantic import BaseModel

from qnetbench.trace.events import (
    ClassicalMessage,
    EntanglementDelivered,
    EntanglementRequested,
    Event,
    QubitSent,
)


class TraceSignature(BaseModel):
    """Demand-signature dimensions measurable from a single trace."""

    # burstiness of the entanglement-request process
    request_cv: float = 0.0  # coefficient of variation of request inter-arrivals
    fano_factor: float = 0.0  # index of dispersion of request counts per bin
    # classical-communication coupling
    msgs_per_pair: float = 0.0
    bytes_per_pair: float = 0.0
    # deadline-criticality (from the demand contracts)
    deadline_fraction: float = 0.0  # fraction of requests carrying a deadline/budget
    min_latency_budget: float | None = None
    # staleness intolerance (tightest tolerated pair age; None = unconstrained)
    min_staleness_tolerance: float | None = None
    # multipartiteness
    n_parties: int = 0


def characterize_trace(events: list[Event]) -> TraceSignature:
    requests = [e for e in events if isinstance(e, EntanglementRequested)]
    delivered = sum(1 for e in events if isinstance(e, EntanglementDelivered))
    sent = [e for e in events if isinstance(e, QubitSent)]  # single-qubit transmissions
    classical = [e for e in events if isinstance(e, ClassicalMessage)]

    sig = TraceSignature()

    # --- burstiness (over the demand events: pair requests and qubit sends) ---
    demand_times = sorted([e.t for e in requests] + [e.t for e in sent])
    gaps = [b - a for a, b in zip(demand_times, demand_times[1:], strict=False)]
    if gaps and statistics.mean(gaps) > 0:
        sig.request_cv = statistics.pstdev(gaps) / statistics.mean(gaps)
    sig.fano_factor = _fano_factor(demand_times)

    # --- classical coupling (per delivered pair or transmitted qubit) ---
    demand_units = delivered + len(sent)
    if demand_units:
        sig.msgs_per_pair = len(classical) / demand_units
        sig.bytes_per_pair = sum(e.n_bytes for e in classical) / demand_units

    # --- deadline-criticality & staleness ---
    if requests:
        with_deadline = sum(
            1
            for e in requests
            if e.demand.deadline is not None or e.demand.latency_budget is not None
        )
        sig.deadline_fraction = with_deadline / len(requests)
        budgets = [e.demand.latency_budget for e in requests if e.demand.latency_budget is not None]
        sig.min_latency_budget = min(budgets) if budgets else None
        tolerances = [
            e.demand.staleness_tolerance
            for e in requests
            if e.demand.staleness_tolerance is not None
        ]
        sig.min_staleness_tolerance = min(tolerances) if tolerances else None

    # --- multipartiteness ---
    nodes = {e.src for e in requests} | {e.dst for e in requests}
    nodes |= {e.src for e in sent} | {e.dst for e in sent}
    sig.n_parties = len(nodes)
    return sig


def _fano_factor(times: list[float], bins: int = 20) -> float:
    """Index of dispersion (variance/mean) of request counts across equal time bins.
    1.0 is Poisson; >1 is bursty, <1 is more regular."""
    if len(times) < 2:
        return 0.0
    span = times[-1] - times[0]
    if span <= 0:
        return 0.0
    width = span / bins
    counts = [0] * bins
    for t in times:
        idx = min(int((t - times[0]) / width), bins - 1)
        counts[idx] += 1
    mean = statistics.mean(counts)
    return statistics.pvariance(counts) / mean if mean > 0 else 0.0
