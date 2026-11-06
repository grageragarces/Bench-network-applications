"""Multi-tenant contention: the cross-policy evaluation (Deliverable 4).

A single application never has more than one pending demand per link, so nothing has
to choose. Scheduling only matters under *contention*: several tenants competing for
a link whose entanglement-generation capacity is below aggregate demand. This module
models that as a queue. Tenants are demand streams read from application traces, not
running applications, and no backend is involved.

A shared link produces one pair per service tick (capacity pairs/second). Tenants
— parameterized by real applications' demand contracts — issue requests over time.
At each tick the chosen `Policy` orders the pending queue and one request is served.
A served request's delivered fidelity decays with how long it waited in queue (the
memory holding its pair decoheres), so a high-`min_fidelity` demand must be served
promptly, while a deadline demand must be served before its deadline. Those two
pressures pull different ways, so which policy wins depends on the workload mix, on
the contract values the tenants declare, and on the metric used to score them.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field, replace

from qnetbench.api.types import Demand
from qnetbench.backends.reference.backend import _age_fidelity
from qnetbench.harness.runner import run_once
from qnetbench.policies import Policy, get_policy
from qnetbench.policies.base import PendingRequest
from qnetbench.trace.events import EntanglementRequested, Event


@dataclass(frozen=True)
class Tenant:
    """A demand stream: an application's contract, issued `n_requests` times at a
    fixed interval."""

    app: str
    min_fidelity: float
    budget: float | None  # relative deadline (s) from each request's arrival, or None
    n_requests: int
    interval: float  # MEAN seconds between this tenant's requests
    # The application's own measured inter-arrival pattern, rescaled to mean 1.0.
    # Arrivals replay this shape at `interval`, so a tenant carries its real
    # burstiness (Section VI's cv and Fano) and not just its contract. Empty means
    # a perfectly regular stream, which is what the earlier fixed-cadence model
    # assumed for every tenant regardless of how the application actually behaves.
    pattern: tuple[float, ...] = ()
    # Offset of this tenant's first request. Without it every tenant starts at
    # t=0, so tenants of the same application — which also share an arrival
    # pattern unless given distinct trace seeds — issue every request at exactly
    # the same instant. That is a thundering herd, not independent multi-tenancy:
    # it maximises queueing by construction and leaves a fidelity-ordered policy
    # nothing to order by, since the contending requests are identical.
    phase: float = 0.0


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


def _arrival_pattern(events: list[Event]) -> tuple[float, ...]:
    """The application's inter-request gaps, normalised to mean 1.0.

    Normalising removes the application's absolute rate (which is a property of the
    backend's link model, not of the workload) while preserving the *shape* of its
    demand process. Two mixes built this way differ in burstiness at identical
    aggregate load, which is what makes burstiness separately testable.
    """
    ts = [ev.t for ev in events if isinstance(ev, EntanglementRequested)]
    gaps = [b - a for a, b in zip(ts, ts[1:], strict=False) if b > a]
    if not gaps:
        return ()
    mean = sum(gaps) / len(gaps)
    return tuple(g / mean for g in gaps) if mean > 0 else ()


def app_profile(
    app: str,
    n_requests: int,
    interval: float,
    *,
    trace_seed: int = 0,
    phase: float = 0.0,
    demand_override: dict[str, object] | None = None,
) -> Tenant:
    """Build a tenant from an application's real demand contract and real arrival
    pattern, both read from an actual run.

    `trace_seed` selects which run the arrival pattern is read from, and `phase`
    offsets the tenant's first request. Two tenants of the same application built
    with the same seed and phase are indistinguishable — same contract, same
    arrival instants — so distinct seeds are what make a mix genuinely
    multi-tenant rather than one stream counted several times. `demand_override`
    is passed to `run_once`, so a tenant's varied contract still comes from a trace.
    """
    events = run_once(app, seed=trace_seed, demand_override=demand_override)
    pattern = _arrival_pattern(events)
    for ev in events:
        if isinstance(ev, EntanglementRequested):
            d = ev.demand
            if d.latency_budget is not None:
                budget: float | None = d.latency_budget
            elif d.deadline is not None:
                budget = d.deadline - ev.t
            else:
                budget = None
            return Tenant(
                app, d.min_fidelity, budget, n_requests, interval, pattern, phase
            )
    raise ValueError(f"application {app!r} issued no entanglement requests")


def arrival_times(tenant: Tenant) -> list[float]:
    """When each of a tenant's requests arrives: its own gap sequence scaled to `interval`."""
    times: list[float] = []
    arrival = tenant.phase
    for k in range(tenant.n_requests):
        if k:
            gap = tenant.pattern[(k - 1) % len(tenant.pattern)] if tenant.pattern else 1.0
            arrival += gap * tenant.interval
        times.append(arrival)
    return times


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
        for arrival in arrival_times(tenant):
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
        # Ask the policy to rank the queue; each request's req_id is its index in
        # `pending`, so order[0] is the position of the request to serve this tick.
        order = policy.order([_to_pending(i, r, t) for i, r in enumerate(pending)], now=t)
        chosen = pending[order[0]]
        # Its delivered fidelity degrades with how long it waited (memory decoheres);
        # the contract is met only if fidelity clears the bar and service beat the deadline.
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
    """Run every mix under every policy. Returns `results[mix][policy]`."""
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


def winning_policies(results: dict[str, ContentionResult]) -> frozenset[str]:
    """Every policy tied for the highest aggregate utility."""
    top = max(r.aggregate_utility for r in results.values())
    return frozenset(p for p, r in results.items() if r.aggregate_utility == top)


def has_inversion(experiment: dict[str, dict[str, ContentionResult]]) -> bool:
    """True if no policy is best on every mix.

    A winner is the set tied for the top score, so a policy tied for best on one mix
    and outright best on another counts as jointly optimal. Taking an arbitrary
    maximum instead would report disagreements that are not there.
    """
    winners = [winning_policies(results) for results in experiment.values()]
    return not frozenset.intersection(*winners)


# The canonical contention operating point (moderate overload; entanglement supply
# below aggregate demand) at which the policy ranking cleanly inverts.
# Moderate overload: below aggregate demand, and representative of the contended
# regime rather than special within it (Section VIII reports the inversion across
# the whole capacity sweep, not at this point alone).
# Operating point for the headline comparison. Capacity sits just below the
# aggregate demand of five tenants at one request per 30 ms (167 req/s), i.e.
# moderate overload. It was raised from 120 when the experiment moved to 100
# requests per tenant: over a longer run the queue no longer drains between
# bursts, so 120 leaves the link under-provisioned (about 10% of contracts met)
# instead of in the contended regime the experiment is meant to probe.
CAPACITY = 160.0
LINK_FIDELITY = 0.99
COHERENCE_TIME = 0.25
# Requests per tenant, and independent arrival draws the headline table averages
# over. Twelve requests quantised the satisfaction rate in units of 1/60, which
# is coarser than the margins being compared.
N_REQUESTS = 100
DRAWS = 32


def default_mixes(
    n_requests: int = 12, interval: float = 0.03, *, seed: int | None = None
) -> dict[str, list[Tenant]]:
    """Two workload classes: one dominated by deadline-critical demand (distributed
    gates), one by fidelity-thresholded demand (BQC + CHSH + QKD).

    `seed=None` keeps the synchronised model: every tenant of an application
    replays the same measured arrival sequence starting at t=0, so four
    `distributed_gate` tenants are one stream counted four times. An integer seed
    gives each tenant its own arrival realisation and start phase, which is what
    "five tenants" ought to mean, and varying it turns a single deterministic
    realisation into a distribution over arrival patterns.
    """
    rng = random.Random(seed) if seed is not None else None

    def group(app: str, count: int) -> list[Tenant]:
        out: list[Tenant] = []
        for _ in range(count):
            if rng is None:
                out.append(app_profile(app, n_requests, interval))
            else:
                out.append(
                    app_profile(
                        app,
                        n_requests,
                        interval,
                        trace_seed=rng.randrange(1 << 30),
                        phase=rng.uniform(0.0, interval),
                    )
                )
        return out

    return {
        "deadline_heavy": group("distributed_gate", 4) + group("qkd", 1),
        "fidelity_heavy": group("bqc", 2) + group("chsh", 2) + group("qkd", 1),
    }


def burstiness_mixes(
    app: str = "heralded_teleport",
    count: int = 5,
    n_requests: int = 12,
    interval: float = 0.03,
    *,
    seed: int | None = None,
) -> dict[str, list[Tenant]]:
    """Two mixes that differ *only* in burstiness.

    Both use the same application, so contracts, tenant count and mean arrival rate
    are identical; the only difference is whether each tenant replays its measured
    inter-arrival pattern or issues on a perfectly regular cadence. This isolates
    the burstiness axis of Section VI, which the fixed-cadence arrival model could
    not express: under it every tenant was smooth regardless of the workload.
    """
    rng = random.Random(seed) if seed is not None else None
    bursty: list[Tenant] = []
    smooth: list[Tenant] = []
    for _ in range(count):
        if rng is None:
            t = app_profile(app, n_requests, interval)
        else:
            t = app_profile(
                app,
                n_requests,
                interval,
                trace_seed=rng.randrange(1 << 30),
                phase=rng.uniform(0.0, interval),
            )
        bursty.append(t)
        # Same tenant, same phase, arrivals evenly spaced instead of replayed:
        # the comparison isolates arrival *shape* and nothing else.
        smooth.append(replace(t, pattern=()))
    return {"bursty": bursty, "smooth": smooth}


@dataclass(frozen=True)
class PolicySummary:
    """One policy on one mix, across every arrival draw."""

    scores: tuple[float, ...]  # aggregate contract satisfaction, one per draw
    per_app: dict[str, float]  # mean satisfaction of each application's tenants

    @property
    def mean(self) -> float:
        return statistics.fmean(self.scores)

    @property
    def std(self) -> float:
        """Sample standard deviation across draws."""
        return statistics.stdev(self.scores) if len(self.scores) > 1 else 0.0

    @property
    def worst_app(self) -> float:
        """Satisfaction of the application this policy serves least. The aggregate
        rate does not penalize a policy for starving one tenant to serve the rest."""
        return min(self.per_app.values())


@dataclass(frozen=True)
class ReplicatedExperiment:
    """Every policy on every mix, replicated over independent arrival draws."""

    draws: int
    n_requests: int
    capacity: float
    link_fidelity: float
    coherence_time: float
    mixes: dict[str, dict[str, PolicySummary]]
    disagreeing_draws: int  # draws in which no policy is best on every mix

    def ranked(self, mix: str) -> list[str]:
        summaries = self.mixes[mix]
        return sorted(summaries, key=lambda p: (-summaries[p].mean, p))

    def separation(self, mix: str) -> float:
        """The leader's lead over the next policy, in standard errors of the difference.
        Paired across draws, since every policy is scored on the same arrivals."""
        first, second = self.ranked(mix)[:2]
        leads = [
            a - b
            for a, b in zip(
                self.mixes[mix][first].scores, self.mixes[mix][second].scores, strict=True
            )
        ]
        error = statistics.stdev(leads) / math.sqrt(len(leads)) if len(leads) > 1 else 0.0
        return statistics.fmean(leads) / error if error > 0.0 else math.inf


def replicated_experiment(
    *,
    draws: int = DRAWS,
    n_requests: int = N_REQUESTS,
    capacity: float = CAPACITY,
    link_fidelity: float = LINK_FIDELITY,
    coherence_time: float = COHERENCE_TIME,
) -> ReplicatedExperiment:
    """The cross-policy evaluation at full scale: independent tenants, replicated
    over `draws` arrival draws, with ties reported as ties."""
    scores: dict[str, dict[str, list[float]]] = {}
    apps: dict[str, dict[str, dict[str, list[float]]]] = {}
    disagreeing = 0
    for seed in range(draws):
        experiment = ranking_experiment(
            default_mixes(n_requests, seed=seed),
            capacity=capacity,
            link_fidelity=link_fidelity,
            coherence_time=coherence_time,
        )
        disagreeing += has_inversion(experiment)
        for mix, results in experiment.items():
            for policy, result in results.items():
                scores.setdefault(mix, {}).setdefault(policy, []).append(result.aggregate_utility)
                per_app = apps.setdefault(mix, {}).setdefault(policy, {})
                for app, value in result.per_app.items():
                    per_app.setdefault(app, []).append(value)
    return ReplicatedExperiment(
        draws=draws,
        n_requests=n_requests,
        capacity=capacity,
        link_fidelity=link_fidelity,
        coherence_time=coherence_time,
        mixes={
            mix: {
                policy: PolicySummary(
                    tuple(values),
                    {app: statistics.fmean(v) for app, v in apps[mix][policy].items()},
                )
                for policy, values in by_policy.items()
            }
            for mix, by_policy in scores.items()
        },
        disagreeing_draws=disagreeing,
    )


def render_replicated(experiment: ReplicatedExperiment) -> str:
    """Contract satisfaction and worst-served application, per policy and mix."""
    mixes = list(experiment.mixes)
    policies = list(next(iter(experiment.mixes.values())))
    width = max(max(len(m) for m in mixes), 15) + 4

    def header(title: str) -> list[str]:
        columns = f"{'policy':16}" + "".join(f"{m:>{width}}" for m in mixes)
        return ["", title, columns, "-" * len(columns)]

    lines = [
        f"{experiment.draws} independent arrival draws, {experiment.n_requests} requests per "
        f"tenant, {experiment.capacity:g} pairs/s,",
        f"link fidelity {experiment.link_fidelity:g}, coherence time "
        f"{experiment.coherence_time:g} s",
        *header("contract satisfaction, mean ± std across draws (* = highest mean)"),
    ]
    for policy in policies:
        row = f"{policy:16}"
        for mix in mixes:
            s = experiment.mixes[mix][policy]
            mark = "*" if experiment.ranked(mix)[0] == policy else " "
            row += f"{f'{s.mean:.3f} ± {s.std:.3f}{mark}':>{width}}"
        lines.append(row)
    lines.append(
        f"{'separation':16}"
        + "".join(f"{f'{experiment.separation(m):.1f} s.e.':>{width}}" for m in mixes)
    )
    lines.extend(header("worst-served application, mean satisfaction"))
    for policy in policies:
        row = f"{policy:16}"
        for mix in mixes:
            row += f"{experiment.mixes[mix][policy].worst_app:>{width}.3f}"
        lines.append(row)
    lines.append("")
    lines.append(
        f"The mixes share no best policy in {experiment.disagreeing_draws} of "
        f"{experiment.draws} draws."
    )
    return "\n".join(lines)


def render_experiment(experiment: dict[str, dict[str, ContentionResult]]) -> str:
    """A policy × workload-mix matrix for one draw, marking every policy tied for best."""
    mixes = list(experiment)
    policies = list(next(iter(experiment.values())))
    width = max(len(m) for m in mixes) + 4

    lines = [f"{'policy':16}" + "".join(f"{m:>{width}}" for m in mixes)]
    lines.append("-" * len(lines[0]))
    winners = {m: winning_policies(experiment[m]) for m in mixes}
    for policy in policies:
        cells = []
        for m in mixes:
            util = experiment[m][policy].aggregate_utility
            mark = "*" if policy in winners[m] else " "
            cells.append(f"{util:>{width - 2}.3f}{mark} ")
        lines.append(f"{policy:16}" + "".join(cells))
    if has_inversion(experiment):
        lines.append("")
        lines.append("No policy is best on every mix.")
    return "\n".join(lines)
