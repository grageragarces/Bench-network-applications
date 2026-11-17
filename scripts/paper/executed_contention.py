"""Run the default contention mixes as real applications, and compare with the queue model.

The queue model (`qnetbench.contention`) assumes what a tenant's service is worth.
This script executes the same applications on one shared link, at the same arrival schedule,
capacity and link fidelity. It moves from the queue model to the agreed execution model one
assumption at a time, so any change in the result can be attributed.

Applications block on each pair, which the queue model does not capture, so there are two
sets of steps. "open" issues each request as its own one-request application, which keeps
the model's open-loop arrivals with real applications running. "blocking" is one long-running
application per tenant. Within each set:

    as model      the queue model's assumptions: queue-wait aging, drop, a fixed tick
    serve late    a missed deadline is served rather than dropped
    held qubits   pairs are fresh, and qubits held by the application decay
    on demand     the link takes a random time per pair rather than a fixed tick

"blocking: on demand" is the agreed model. Its utility is what the applications measured.

    python scripts/paper/executed_contention.py --draws 32
    python scripts/paper/executed_contention.py --sweep 60,80,100,120,140,160,200 --draws 16
"""

from __future__ import annotations

import argparse
import multiprocessing
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from qnetbench.characterize.provenance import write_atomic
from qnetbench.contention import (
    CAPACITY,
    COHERENCE_TIME,
    DRAWS,
    LINK_FIDELITY,
    N_REQUESTS,
    ContentionResult,
    Tenant,
    arrival_times,
    default_mixes,
    has_inversion,
    simulate,
)
from qnetbench.policies import get_policy
from qnetbench.tenancy import (
    AS_QUEUE_MODEL,
    ExecutionModel,
    TenantSpec,
    application_utility,
    contract_satisfaction,
    queue_model_on_link,
    run_tenants,
)
from qnetbench.topology import LinkModel

POLICIES = ("fifo", "fidelity_first", "edf")
CLASSICAL_LATENCY = 1e-3  # the corpus default, kept apart from the link's service rate
DATA = Path(__file__).parent / "data"

# How to make each application issue a given number of requests.
REQUEST_COUNT = {"distributed_gate": "reps", "qkd": "rounds", "bqc": "depth", "chsh": "rounds"}

_SERVE_LATE = ExecutionModel(aging="queue_wait", service="ticks")
_HELD = ExecutionModel(service="ticks")
_AGREED = ExecutionModel()


@dataclass(frozen=True)
class Step:
    name: str
    model: ExecutionModel | None  # None is the queue model itself
    open_loop: bool = False


STEPS = (
    Step("queue model", None),
    Step("open: as model", AS_QUEUE_MODEL, True),
    Step("open: serve late", _SERVE_LATE, True),
    Step("open: held qubits", _HELD, True),
    Step("open: on demand", _AGREED, True),
    Step("blocking: as model", AS_QUEUE_MODEL),
    Step("blocking: serve late", _SERVE_LATE),
    Step("blocking: held qubits", _HELD),
    Step("blocking: on demand", _AGREED),
    Step("  with depolarizing", ExecutionModel(memory_noise="depolarizing")),
)
AGREED = "blocking: on demand"
SWEEP_STEPS = ("queue model", "open: on demand", "blocking: as model", AGREED)


@dataclass(frozen=True)
class Score:
    satisfaction: float
    per_app_satisfaction: dict[str, float]
    per_app_utility: dict[str, float]

    @property
    def worst_app(self) -> float:
        return min(self.per_app_satisfaction.values())

    @property
    def utility(self) -> float:
        return statistics.fmean(self.per_app_utility.values())


Draw = dict[str, dict[str, dict[str, Score]]]  # step, mix, policy


def _by_app(apps: Sequence[str], values: Sequence[float]) -> dict[str, float]:
    grouped: dict[str, list[float]] = {}
    for app, value in zip(apps, values, strict=True):
        grouped.setdefault(app, []).append(value)
    return {app: statistics.fmean(v) for app, v in grouped.items()}


def _specs(tenants: Sequence[Tenant], *, open_loop: bool) -> list[TenantSpec]:
    specs: list[TenantSpec] = []
    for i, tenant in enumerate(tenants):
        times = tuple(arrival_times(tenant))
        key = REQUEST_COUNT[tenant.app]
        if open_loop:
            specs += [
                TenantSpec(f"{tenant.app}-{i}-{k}", tenant.app, {key: 1}, arrivals=(when,))
                for k, when in enumerate(times)
            ]
        else:
            specs.append(
                TenantSpec(f"{tenant.app}-{i}", tenant.app, {key: tenant.n_requests}, times)
            )
    return specs


def execute(
    tenants: Sequence[Tenant], policy: str, step: Step, seed: int, *, capacity: float
) -> Score:
    assert step.model is not None
    specs = _specs(tenants, open_loop=step.open_loop)
    run = run_tenants(
        specs,
        seed=seed,
        arbitration=f"policy:{policy}",
        link=LinkModel(1.0 / capacity, LINK_FIDELITY, 0.0),
        classical_latency=CLASSICAL_LATENCY,
        coherence_time=COHERENCE_TIME,
        model=step.model,
    )
    apps = [s.app for s in specs]
    satisfaction = [contract_satisfaction(run.traces[s.name]) for s in specs]
    # One request is no sample of what an application is for, so open-loop utility is not read.
    utility = [] if step.open_loop else [application_utility(run.traces[s.name]) for s in specs]
    return Score(
        statistics.fmean(satisfaction),
        _by_app(apps, satisfaction),
        _by_app(apps, utility) if utility else {},
    )


def _queue_model(tenants: Sequence[Tenant], policy: str, capacity: float) -> Score:
    params = {
        "capacity": capacity,
        "link_fidelity": LINK_FIDELITY,
        "coherence_time": COHERENCE_TIME,
    }
    result = simulate(list(tenants), get_policy(policy), **params)
    # The server has to agree with the model before anything runs on it.
    check = queue_model_on_link(tenants, get_policy(policy), **params)
    assert check.aggregate_utility == result.aggregate_utility
    assert check.per_app == result.per_app
    return Score(result.aggregate_utility, dict(result.per_app), {})


def score_draw(args: tuple[int, int, float, tuple[str, ...]]) -> Draw:
    """The chosen steps, for every mix and policy, on one arrival draw."""
    draw, n_requests, capacity, names = args
    mixes = default_mixes(n_requests, seed=draw)
    out: Draw = {}
    for step in STEPS:
        if step.name not in names:
            continue
        out[step.name] = {
            mix: {
                policy: (
                    _queue_model(tenants, policy, capacity)
                    if step.model is None
                    else execute(tenants, policy, step, draw, capacity=capacity)
                )
                for policy in POLICIES
            }
            for mix, tenants in mixes.items()
        }
    return out


def _disagrees(by_mix: dict[str, dict[str, Score]], read: Callable[[Score], float]) -> bool:
    """Is there no policy tied for best on every mix? Scores equal to 9 places are ties."""
    results = {
        mix: {
            p: ContentionResult(policy=p, aggregate_utility=round(read(s), 9))
            for p, s in scores.items()
        }
        for mix, scores in by_mix.items()
    }
    return has_inversion(results)


def _mean(draws: list[Draw], step: str, mix: str, policy: str, read) -> float:
    return statistics.fmean(read(d[step][mix][policy]) for d in draws)


def render(draws: list[Draw], args: argparse.Namespace) -> str:
    mixes = list(draws[0]["queue model"])
    names = [s.name for s in STEPS]
    lines = [
        f"{len(draws)} arrival draws, {args.requests} requests per tenant, {args.capacity:g} "
        f"pairs/s, link fidelity {LINK_FIDELITY}, coherence time {COHERENCE_TIME} s,",
        f"classical latency {CLASSICAL_LATENCY} s. Satisfaction counts fidelity and deadline, as "
        "the queue model does, and ignores staleness.",
    ]

    def table(title: str, read, steps: list[str]) -> None:
        nonlocal lines
        lines += ["", title]
        for mix in mixes:
            lines.append(f"  {mix}")
            lines.append(f"    {'step':24}" + "".join(f"{p:>16}" for p in POLICIES))
            for step in steps:
                row = "".join(f"{_mean(draws, step, mix, p, read):>16.3f}" for p in POLICIES)
                lines.append(f"    {step:24}{row}")

    table("Contract satisfaction", lambda s: s.satisfaction, names)
    table("Worst-served application, satisfaction", lambda s: s.worst_app, names)
    blocking = [s.name for s in STEPS if s.model is not None and not s.open_loop]
    table("Mean application utility, as measured", lambda s: s.utility, blocking)

    lines += ["", "Draws in which no policy is best on both mixes (ties count as ties)"]
    for step in names:
        count = sum(_disagrees(d[step], lambda s: s.satisfaction) for d in draws)
        lines.append(f"    {step:24}{count:>4} of {len(draws)}")

    lines += ["", f"Application utility per application ({AGREED})"]
    for mix in mixes:
        lines.append(f"  {mix}")
        lines.append(f"    {'application':24}" + "".join(f"{p:>16}" for p in POLICIES))
        for app in draws[0][AGREED][mix][POLICIES[0]].per_app_utility:
            read = lambda s, a=app: s.per_app_utility[a]  # noqa: E731
            row = "".join(f"{_mean(draws, AGREED, mix, p, read):>16.3f}" for p in POLICIES)
            lines.append(f"    {app:24}{row}")
    return "\n".join(lines) + "\n"


def render_sweep(results: dict[float, list[Draw]], args: argparse.Namespace) -> str:
    steps = list(SWEEP_STEPS)
    lines = [
        f"Capacity sweep: {args.draws} arrival draws, {args.requests} requests per tenant. "
        "Aggregate demand is about 167 requests/s.",
        "",
        "Draws in which no policy is best on both mixes (ties count as ties)",
        f"  {'pairs/s':>8}" + "".join(f"{s:>24}" for s in steps),
    ]
    for capacity, draws in results.items():
        row = "".join(
            f"{sum(_disagrees(d[s], lambda x: x.satisfaction) for d in draws):>24}" for s in steps
        )
        lines.append(f"  {capacity:>8g}{row}")

    for step in steps:
        lines += ["", f"Contract satisfaction: {step}"]
        for mix in next(iter(results.values()))[0][step]:
            lines.append(f"  {mix}")
            lines.append(f"    {'pairs/s':>8}" + "".join(f"{p:>16}" for p in POLICIES))
            for capacity, draws in results.items():
                row = "".join(
                    f"{_mean(draws, step, mix, p, lambda s: s.satisfaction):>16.3f}"
                    for p in POLICIES
                )
                lines.append(f"    {capacity:>8g}{row}")

    lines += ["", f"Mean application utility: {AGREED}"]
    for mix in next(iter(results.values()))[0][AGREED]:
        lines.append(f"  {mix}")
        lines.append(f"    {'pairs/s':>8}" + "".join(f"{p:>16}" for p in POLICIES))
        for capacity, draws in results.items():
            row = "".join(
                f"{_mean(draws, AGREED, mix, p, lambda s: s.utility):>16.3f}" for p in POLICIES
            )
            lines.append(f"    {capacity:>8g}{row}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--draws", type=int, default=DRAWS)
    parser.add_argument("--requests", type=int, default=N_REQUESTS)
    parser.add_argument("--capacity", type=float, default=CAPACITY)
    parser.add_argument("--sweep", type=str, default="", help="comma-separated capacities")
    parser.add_argument("--jobs", type=int, default=max(1, (multiprocessing.cpu_count() or 2) - 1))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    with multiprocessing.Pool(args.jobs) as pool:
        if args.sweep:
            names = SWEEP_STEPS
            results: dict[float, list[Draw]] = {}
            for capacity in (float(c) for c in args.sweep.split(",")):
                work = [(d, args.requests, capacity, names) for d in range(args.draws)]
                results[capacity] = pool.map(score_draw, work)
            text = render_sweep(results, args)
            out = args.out or DATA / "executed_contention_sweep.txt"
        else:
            names = tuple(s.name for s in STEPS)
            work = [(d, args.requests, args.capacity, names) for d in range(args.draws)]
            text = render(pool.map(score_draw, work), args)
            out = args.out or DATA / "executed_contention.txt"
    write_atomic(out, text)
    print(text)


if __name__ == "__main__":
    main()
