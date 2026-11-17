"""Three supplies at one link description, running the default contention mixes.

Same rate, same fidelity and same classical delay on all three, so what differs is the timing
of the pairs: exponential on the reference supply, fixed on NetSquid, and whatever SeQUeNCe's
protocol does. This is the like-for-like test of what a simulator adds.

Free-running links are the one physical setting where a pair really does age before delivery,
so they also test whether any such aging brings back the disagreement between mixes.

The two simulators need different environments, so run once in each:

    .venv/bin/python scripts/paper/three_supplies.py --supplies reference,sequence
    .venv-ns/bin/python scripts/paper/three_supplies.py --supplies netsquid
    .venv/bin/python scripts/paper/three_supplies.py --sweep 60,100,140,160,200,300,600
"""

from __future__ import annotations

import argparse
import math
import multiprocessing
import statistics
from dataclasses import dataclass
from pathlib import Path

from qnetbench.characterize.provenance import write_atomic
from qnetbench.contention import (
    COHERENCE_TIME,
    LINK_FIDELITY,
    ContentionResult,
    arrival_times,
    default_mixes,
    has_inversion,
)
from qnetbench.tenancy import (
    ExecutionModel,
    TenantSpec,
    _supply_backend,
    application_utility,
    contract_satisfaction,
    run_tenants,
)
from qnetbench.topology import LinkModel
from qnetbench.trace.events import EntanglementDelivered

DATA = Path(__file__).parent / "data"
POLICIES = ("fifo", "fidelity_first", "edf")
CLASSICAL_LATENCY = 1e-3
RATE = 153.0  # what SeQUeNCe achieves with two memories at this classical delay
REQUESTS = 100
WINDOW = 12.0
REQUEST_COUNT = {"distributed_gate": "reps", "qkd": "rounds", "bqc": "depth", "chsh": "rounds"}
MODELS = {
    "on demand": ExecutionModel(),
    "free running, 1 pair": ExecutionModel(service="free_running", storage=1),
    "free running, 10 pairs": ExecutionModel(service="free_running", storage=10),
    "free running, 10 pairs, oldest first": ExecutionModel(
        service="free_running", storage=10, stored_pair="oldest"
    ),
}


@dataclass(frozen=True)
class Score:
    satisfaction: float
    with_staleness: float
    worst_app: float
    utility: float
    mean_age_ms: float


OPTIONS: dict[str, dict] = {"netsquid-exponential": {"timing": "exponential"}}


def _base(supply: str) -> str:
    return supply.split("-")[0]


def _score(args: tuple[str, str, str, str, int, float]) -> tuple[str, str, str, str, int, Score]:
    supply, model_name, mix, policy, draw, rate = args
    tenants = default_mixes(REQUESTS, seed=draw)[mix]
    specs = [
        TenantSpec(
            f"{t.app}-{i}",
            t.app,
            {REQUEST_COUNT[t.app]: t.n_requests},
            tuple(arrival_times(t)),
        )
        for i, t in enumerate(tenants)
    ]
    run = run_tenants(
        specs,
        seed=draw,
        arbitration=f"policy:{policy}",
        link=LinkModel(1.0 / rate, LINK_FIDELITY, 0.0),
        classical_latency=CLASSICAL_LATENCY,
        coherence_time=COHERENCE_TIME,
        model=MODELS[model_name],
        supply=_base(supply),
        supply_window=WINDOW,
        supply_options=OPTIONS.get(supply),
    )
    traces = [run.traces[s.name] for s in specs]
    satisfaction = [contract_satisfaction(t) for t in traces]
    by_app: dict[str, list[float]] = {}
    for spec, value in zip(specs, satisfaction, strict=True):
        by_app.setdefault(spec.app, []).append(value)
    ages = [e.pair_age for t in traces for e in t if isinstance(e, EntanglementDelivered)]
    return (
        supply,
        model_name,
        mix,
        policy,
        draw,
        Score(
            statistics.fmean(satisfaction),
            statistics.fmean(contract_satisfaction(t, ignore=()) for t in traces),
            min(statistics.fmean(v) for v in by_app.values()),
            statistics.fmean(application_utility(t) for t in traces),
            statistics.fmean(ages) * 1e3,
        ),
    )


def _timing(args: tuple[str, float]) -> str:
    supply, rate = args
    backend = _supply_backend(
        _base(supply),
        LinkModel(1.0 / rate, LINK_FIDELITY, 0.0),
        CLASSICAL_LATENCY,
        1,
        2.0,
        **OPTIONS.get(supply, {}),
    )
    if supply == "reference":
        gaps, fidelities = [], []
        for _ in range(4000):
            gap, sampled = backend._sample_pairs("alice", "bob", 1)
            gaps.append(gap)
            fidelities += sampled
    else:
        stream = next(iter(backend._cursors.values())).supply  # type: ignore[attr-defined]
        gaps, fidelities = stream.inter_arrivals[1:], stream.fidelities
    mean = statistics.fmean(gaps)
    median = statistics.median(gaps)
    ratio = mean / median if median > 0 else math.inf
    return (
        f"  {supply:22}{1 / mean:>9.1f} pairs/s   mean gap {mean * 1e3:>6.2f} ms   "
        f"cv {statistics.stdev(gaps) / mean:>5.2f}   mean/median {ratio:>5.2f}   "
        f"F {statistics.fmean(fidelities):.4f}"
    )


def _disagrees(scores: dict[str, dict[str, Score]]) -> bool:
    results = {
        mix: {
            p: ContentionResult(policy=p, aggregate_utility=round(s.satisfaction, 9))
            for p, s in by_policy.items()
        }
        for mix, by_policy in scores.items()
    }
    return has_inversion(results)


def _table(results: dict, draws: int, group_label: str) -> list[str]:
    lines: list[str] = []
    for group, by_model in results.items():
        for model_name, by_mix in by_model.items():
            lines += ["", f"{group_label} {group}, {model_name}"]
            lines.append(f"  {'':16}{'':8}" + "".join(f"{p:>16}" for p in POLICIES))
            for mix, by_policy in by_mix.items():
                for label, read in (
                    ("satisfaction", lambda s: s.satisfaction),
                    ("+ staleness", lambda s: s.with_staleness),
                    ("worst served", lambda s: s.worst_app),
                    ("utility", lambda s: s.utility),
                    ("pair age, ms", lambda s: s.mean_age_ms),
                ):
                    row = "".join(
                        f"{statistics.fmean(read(by_policy[p][d]) for d in range(draws)):>16.3f}"
                        for p in POLICIES
                    )
                    lines.append(f"  {mix:16}{label:<14}"[:32].ljust(24) + row)
            count = sum(
                _disagrees(
                    {
                        mix: {p: by_mix[mix][p][d] for p in POLICIES}
                        for mix in by_mix
                    }
                )
                for d in range(draws)
            )
            lines.append(f"  draws with no policy best on both mixes: {count} of {draws}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--supplies", default="reference")
    parser.add_argument("--sweep", default="", help="comma-separated rates, reference supply only")
    parser.add_argument("--draws", type=int, default=16)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    mixes = list(default_mixes(2, seed=0))

    if args.sweep:
        groups = [("reference", float(r)) for r in args.sweep.split(",")]
        label = "reference supply at pairs/s:"
    else:
        groups = [(s, RATE) for s in args.supplies.split(",")]
        label = "supply:"

    with multiprocessing.Pool() as pool:
        timing = [] if args.sweep else pool.map(_timing, groups)
        results: dict = {}
        for supply, rate in groups:
            key = f"{rate:g}" if args.sweep else supply
            work = [
                (supply, model_name, mix, policy, draw, rate)
                for model_name in MODELS
                for mix in mixes
                for policy in POLICIES
                for draw in range(args.draws)
            ]
            for _, model_name, mix, policy, draw, score in pool.map(_score, work):
                results.setdefault(key, {}).setdefault(model_name, {}).setdefault(
                    mix, {}
                ).setdefault(policy, {})[draw] = score

    lines = [
        f"{args.draws} arrival draws, {REQUESTS} requests per tenant, link fidelity "
        f"{LINK_FIDELITY}, classical delay {CLASSICAL_LATENCY} s,",
        f"dephasing memory at {COHERENCE_TIME} s. Satisfaction counts fidelity and deadline; "
        "'+ staleness' also counts staleness.",
    ]
    if timing:
        lines += ["", f"Timing of each supply, asked for {RATE:g} pairs/s:", *timing]
    lines += _table(results, args.draws, label)
    text = "\n".join(lines) + "\n"
    default = "three_supplies_sweep.txt" if args.sweep else f"three_supplies_{groups[0][0]}.txt"
    write_atomic(args.out or DATA / default, text)
    print(text)


if __name__ == "__main__":
    main()
