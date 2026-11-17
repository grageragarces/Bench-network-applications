"""Published schedulers on one shared workload, and under the authors' own kind of workload.

    python scripts/paper/scheduler_comparison.py

1. Persistent flows, as Ercetin and Gedik use: eight always-backlogged tenants, scored on their
   own metrics (mean age, 95th-percentile age, CVaR, throughput, Jain, starvation). They use a 3x3
   grid and path diversity, which a single link cannot represent, so this checks what transfers
   and does not reproduce their numbers.
2. The two default mixes on the agreed execution model.
3. Three memory-sensitive dqc tenants with a gates background.
"""

from __future__ import annotations

import math
import multiprocessing
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fidelity_age_policies import register_all  # noqa: E402

from qnetbench.characterize.provenance import write_atomic  # noqa: E402
from qnetbench.contention import (  # noqa: E402
    COHERENCE_TIME,
    LINK_FIDELITY,
    arrival_times,
    default_mixes,
)
from qnetbench.tenancy import (  # noqa: E402
    ExecutionModel,
    TenantSpec,
    application_utility,
    contract_satisfaction,
    run_tenants,
)
from qnetbench.topology import LinkModel  # noqa: E402
from qnetbench.trace.events import EntanglementDelivered  # noqa: E402

OUT = Path(__file__).parent / "data" / "scheduler_comparison.txt"
RATE = 160.0
SLOT = 1.0 / RATE
LINK = LinkModel(SLOT, LINK_FIDELITY, 0.0)
POLICIES = (
    "fifo",
    "tp_max",
    "fid_max",
    "fa_index_printed",
    "fa_index_intended",
    "fa_thr",
    "fidelity_first",
    "edf",
)
REQUEST_COUNT = {"distributed_gate": "reps", "qkd": "rounds", "bqc": "depth", "chsh": "rounds"}
FLOWS = 8
FLOW_REQUESTS = 200


def _setup() -> None:
    register_all(slot=SLOT)


def _ages(times: list[float], end: float) -> list[float]:
    """A flow's age at each slot, in slots, from the time since its last delivery."""
    ages: list[float] = []
    last = 0.0
    position = 0
    for k in range(int(end / SLOT)):
        now = k * SLOT
        while position < len(times) and times[position] <= now:
            last = times[position]
            position += 1
        ages.append((now - last) / SLOT)
    return ages


def _persistent(args: tuple[str, int]) -> tuple[str, int, dict[str, float]]:
    policy, seed = args
    tenants = [TenantSpec(f"f{i}", "qkd", {"rounds": FLOW_REQUESTS}) for i in range(FLOWS)]
    model = ExecutionModel(arrivals="closed_loop")
    run = run_tenants(
        tenants,
        seed=seed,
        arbitration=f"policy:{policy}",
        link=LINK,
        classical_latency=1e-3,
        coherence_time=COHERENCE_TIME,
        model=model,
    )
    deliveries = {
        name: [e.t for e in trace if isinstance(e, EntanglementDelivered)]
        for name, trace in run.traces.items()
    }
    # Score to the moment the first flow finishes. After that the link is no longer contended,
    # and every flow would be credited with the service it gets once the others have gone.
    end = min(times[-1] for times in deliveries.values())
    per_flow = {name: _ages(times, end) for name, times in deliveries.items()}
    means = [statistics.fmean(ages) for ages in per_flow.values()]
    pooled = sorted(a for ages in per_flow.values() for a in ages)
    a95 = pooled[int(0.95 * (len(pooled) - 1))]
    tail = [a for a in pooled if a > a95] or [a95]
    inverse = [1.0 / (1.0 + m) for m in means]
    served = sum(sum(t <= end for t in times) for times in deliveries.values())
    # Ercetin and Gedik's A_ref is the 95th-percentile age of a single-flow baseline. A flow alone here
    # is served every slot on average, so its age is about one slot and A_ref is small.
    reference = 3.0
    return (
        policy,
        seed,
        {
            "mean age": statistics.fmean(means),
            "A95": a95,
            "CVaR95": statistics.fmean(tail),
            "throughput": served / (end / SLOT),
            "Jain": sum(inverse) ** 2 / (len(inverse) * sum(x * x for x in inverse)),
            "starved": sum(m > FLOWS * reference for m in means) / len(means),
        },
    )


def _mix(args: tuple[str, str, int]) -> tuple[str, str, int, tuple[float, float, float]]:
    mix, policy, seed = args
    tenants = default_mixes(100, seed=seed)[mix]
    specs = [
        TenantSpec(
            f"{t.app}-{i}", t.app, {REQUEST_COUNT[t.app]: t.n_requests}, tuple(arrival_times(t))
        )
        for i, t in enumerate(tenants)
    ]
    run = run_tenants(
        specs,
        seed=seed,
        arbitration=f"policy:{policy}",
        link=LINK,
        classical_latency=1e-3,
        coherence_time=COHERENCE_TIME,
    )
    by_app: dict[str, list[float]] = {}
    for spec in specs:
        by_app.setdefault(spec.app, []).append(contract_satisfaction(run.traces[spec.name]))
    satisfaction = statistics.fmean(contract_satisfaction(run.traces[s.name]) for s in specs)
    utility = statistics.fmean(application_utility(run.traces[s.name]) for s in specs)
    worst = min(statistics.fmean(v) for v in by_app.values())
    return mix, policy, seed, (satisfaction, worst, utility)


def _sensitive(args: tuple[str, int]) -> tuple[str, int, float, float]:
    policy, seed = args
    names = ("dqc_qft4", "dqc_qft4", "dqc_random4")
    tenants = [TenantSpec(f"s{i}", name) for i, name in enumerate(names)] + [
        TenantSpec(f"bg{i}", "distributed_gate", {"reps": 64}) for i in range(2)
    ]
    run = run_tenants(
        tenants,
        seed=seed,
        arbitration=f"policy:{policy}",
        link=LINK,
        classical_latency=1e-3,
        coherence_time=COHERENCE_TIME,
    )
    return (
        policy,
        seed,
        statistics.fmean(application_utility(run.traces[f"s{i}"]) for i in range(3)),
        statistics.fmean(application_utility(run.traces[f"bg{i}"]) for i in range(2)),
    )


def main() -> None:
    _setup()
    seeds = 16
    with multiprocessing.Pool(initializer=_setup) as pool:
        persistent = pool.map(_persistent, [(p, s) for p in POLICIES for s in range(seeds)])
        mixes = pool.map(
            _mix,
            [
                (m, p, s)
                for m in ("deadline_heavy", "fidelity_heavy")
                for p in POLICIES
                for s in range(seeds)
            ],
        )
        sensitive = pool.map(_sensitive, [(p, s) for p in POLICIES for s in range(128)])

    lines = [f"1. {FLOWS} persistent qkd flows, {RATE:g} pairs/s, {seeds} seeds. Age in slots."]
    keys = ("mean age", "A95", "CVaR95", "throughput", "Jain", "starved")
    lines.append(f"   {'policy':20}" + "".join(f"{k:>12}" for k in keys))
    for policy in POLICIES:
        rows = [m for p, _, m in persistent if p == policy]
        lines.append(
            f"   {policy:20}"
            + "".join(f"{statistics.fmean(r[k] for r in rows):>12.3f}" for k in keys)
        )

    lines += ["", f"2. The default mixes on the agreed model, {seeds} seeds."]
    for mix in ("deadline_heavy", "fidelity_heavy"):
        lines.append(f"   {mix}")
        lines.append(f"     {'policy':20}{'satisfaction':>14}{'worst served':>14}{'utility':>10}")
        for policy in POLICIES:
            rows = [v for m, p, _, v in mixes if m == mix and p == policy]
            lines.append(
                f"     {policy:20}{statistics.fmean(r[0] for r in rows):>14.3f}"
                f"{statistics.fmean(r[1] for r in rows):>14.3f}"
                f"{statistics.fmean(r[2] for r in rows):>10.3f}"
            )

    lines += ["", "3. Three dqc tenants with a gates background, 128 seeds."]
    lines.append(f"     {'policy':20}{'dqc utility':>18}{'gate utility':>14}")
    for policy in POLICIES:
        rows = [(d, b) for p, _, d, b in sensitive if p == policy]
        values = [d for d, _ in rows]
        se = statistics.stdev(values) / math.sqrt(len(values))
        cell = f"{statistics.fmean(values):.3f} ± {se:.3f}"
        lines.append(f"     {policy:20}{cell:>18}{statistics.fmean(b for _, b in rows):>14.3f}")
    text = "\n".join(lines) + "\n"
    write_atomic(OUT, text)
    print(text)


if __name__ == "__main__":
    main()
