"""Multi-tenant contention: the cross-policy ranking-inversion result (Deliverable 4).

The earlier phases run one application at a time, so the arbiter never has to
choose — there is only ever one pending demand. Scheduling only matters under
*contention*: several tenants competing for a link whose entanglement-generation
capacity is below aggregate demand. This module runs that experiment.

A shared link produces one pair per service tick (capacity pairs/second). Tenants
— parameterized by real applications' demand contracts — issue requests over time.
At each tick the chosen `Policy` orders the pending queue and one request is served.
A served request's delivered fidelity decays with how long it waited in queue (the
memory holding its pair decoheres), so a high-`min_fidelity` demand must be served
promptly, while a deadline demand must be served before its deadline. Those two
pressures pull different ways, so the policy that wins depends on the workload mix —
and the ranking *inverts* between a deadline-heavy and a fidelity-heavy mix. That
inversion is the proof that single-workload evaluation produces unreliable rankings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from qnetbench.api.types import Demand
from qnetbench.backends.reference.backend import _age_fidelity
from qnetbench.harness.runner import run_once
from qnetbench.policies import Policy, get_policy
from qnetbench.policies.base import PendingRequest
from qnetbench.trace.events import EntanglementRequested


@dataclass(frozen=True)
class Tenant:
    """A demand stream: an application's contract, issued `n_requests` times at a
    fixed interval."""

    app: str
    min_fidelity: float
    budget: float | None  # relative deadline (s) from each request's arrival, or None
    n_requests: int
    interval: float  # seconds between this tenant's requests


@dataclass
class ContentionResult:
    policy: str
    aggregate_utility: float = 0.0  # fraction of requests whose contract was met
    violation_rate: float = 0.0
    per_app: dict[str, float] = field(default_factory=dict)


@dataclass
class _Req:
    app: str
    arrival: float
    min_fidelity: float
    deadline: float  # math.inf if none
    met: bool = False


def app_profile(app: str, n_requests: int, interval: float) -> Tenant:
    """Build a tenant from an application's real demand contract (read from a run)."""
    events = run_once(app, seed=0)
    for ev in events:
        if isinstance(ev, EntanglementRequested):
            d = ev.demand
            if d.latency_budget is not None:
                budget: float | None = d.latency_budget
            elif d.deadline is not None:
                budget = d.deadline - ev.t
            else:
                budget = None
            return Tenant(app, d.min_fidelity, budget, n_requests, interval)
    raise ValueError(f"application {app!r} issued no entanglement requests")


def simulate(
    tenants: list[Tenant],
    policy: Policy,
    *,
    capacity: float,
    link_fidelity: float,
    coherence_time: float,
) -> ContentionResult:
    """Discrete-event contention simulation over one shared link."""
    requests: list[_Req] = []
    for tenant in tenants:
        for k in range(tenant.n_requests):
            arrival = k * tenant.interval
            deadline = arrival + tenant.budget if tenant.budget is not None else math.inf
            requests.append(_Req(tenant.app, arrival, tenant.min_fidelity, deadline))
    requests.sort(key=lambda r: r.arrival)

    dt = 1.0 / capacity
    horizon = max((r.arrival for r in requests), default=0.0) + dt
    n_ticks = int(horizon / dt) + len(requests) + 1  # enough ticks to drain the queue

    pending: list[_Req] = []
    idx = 0
    for tick in range(n_ticks):
        t = tick * dt
        while idx < len(requests) and requests[idx].arrival <= t:
            pending.append(requests[idx])
            idx += 1
        pending = [r for r in pending if r.deadline >= t]  # expired = violation (met stays False)
        if not pending:
            if idx >= len(requests):
                break
            continue
        order = policy.order([_to_pending(i, r, t) for i, r in enumerate(pending)], now=t)
        chosen = pending[order[0]]
        wait = t - chosen.arrival
        delivered = _age_fidelity(link_fidelity, wait, coherence_time)
        chosen.met = delivered >= chosen.min_fidelity and t <= chosen.deadline
        pending.remove(chosen)

    met = sum(1 for r in requests if r.met)
    total = len(requests)
    result = ContentionResult(policy=policy.name)
    result.aggregate_utility = met / total if total else 0.0
    result.violation_rate = 1.0 - result.aggregate_utility
    for app in {r.app for r in requests}:
        app_reqs = [r for r in requests if r.app == app]
        result.per_app[app] = sum(1 for r in app_reqs if r.met) / len(app_reqs)
    return result


def _to_pending(idx: int, req: _Req, now: float) -> PendingRequest:
    deadline = req.deadline if math.isfinite(req.deadline) else None
    return PendingRequest(
        req_id=idx,
        src="t",
        dst="l",
        n=1,
        demand=Demand(min_fidelity=req.min_fidelity, deadline=deadline),
        request_time=req.arrival,
    )


def ranking_experiment(
    mixes: dict[str, list[Tenant]],
    *,
    policies: tuple[str, ...] = ("fifo", "fidelity_first", "edf"),
    capacity: float,
    link_fidelity: float,
    coherence_time: float,
) -> dict[str, dict[str, ContentionResult]]:
    """Run every mix under every policy. Returns results[mix][policy]."""
    out: dict[str, dict[str, ContentionResult]] = {}
    for mix_name, tenants in mixes.items():
        out[mix_name] = {
            name: simulate(
                tenants,
                get_policy(name),
                capacity=capacity,
                link_fidelity=link_fidelity,
                coherence_time=coherence_time,
            )
            for name in policies
        }
    return out


def best_policy(results: dict[str, ContentionResult]) -> str:
    """The policy with the highest aggregate utility for one mix."""
    return max(results, key=lambda p: results[p].aggregate_utility)


def has_inversion(experiment: dict[str, dict[str, ContentionResult]]) -> bool:
    """True if the winning policy differs across mixes (a ranking inversion)."""
    winners = {best_policy(res) for res in experiment.values()}
    return len(winners) > 1


# The canonical contention operating point (moderate overload; entanglement supply
# below aggregate demand) at which the policy ranking cleanly inverts.
CAPACITY = 110.0
LINK_FIDELITY = 0.99
COHERENCE_TIME = 0.25


def default_mixes(n_requests: int = 12, interval: float = 0.03) -> dict[str, list[Tenant]]:
    """Two workload classes: one dominated by deadline-critical demand (distributed
    gates), one by fidelity-thresholded demand (BQC + CHSH + QKD)."""

    def group(app: str, count: int) -> list[Tenant]:
        return [app_profile(app, n_requests, interval) for _ in range(count)]

    return {
        "deadline_heavy": group("distributed_gate", 4) + group("qkd", 1),
        "fidelity_heavy": group("bqc", 2) + group("chsh", 2) + group("qkd", 1),
    }


def default_experiment() -> dict[str, dict[str, ContentionResult]]:
    """The headline cross-policy evaluation (Deliverable 4)."""
    return ranking_experiment(
        default_mixes(),
        capacity=CAPACITY,
        link_fidelity=LINK_FIDELITY,
        coherence_time=COHERENCE_TIME,
    )


def render_experiment(experiment: dict[str, dict[str, ContentionResult]]) -> str:
    """A policy × workload-mix utility matrix, marking each mix's winner (*)."""
    mixes = list(experiment)
    policies = list(next(iter(experiment.values())))
    width = max(len(m) for m in mixes) + 4

    lines = [f"{'policy':16}" + "".join(f"{m:>{width}}" for m in mixes)]
    lines.append("-" * len(lines[0]))
    winners = {m: best_policy(experiment[m]) for m in mixes}
    for policy in policies:
        cells = []
        for m in mixes:
            util = experiment[m][policy].aggregate_utility
            mark = "*" if winners[m] == policy else " "
            cells.append(f"{util:>{width - 2}.3f}{mark} ")
        lines.append(f"{policy:16}" + "".join(cells))
    lines.append(f"{'winner':16}" + "".join(f"{winners[m]:>{width}}" for m in mixes))

    if has_inversion(experiment):
        verdict = "  →  ".join(f"{m}: {winners[m]}" for m in mixes)
        lines.append("")
        lines.append(f"RANKING INVERSION — the best policy flips across workloads ({verdict}).")
        lines.append(
            "Single-workload evaluation would have crowned one policy and been wrong on the other."
        )
    return "\n".join(lines)
