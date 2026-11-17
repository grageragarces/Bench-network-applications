"""Where can a scheduler change what applications achieve?

`executed_contention.py` finds that on the default mixes the policy changes contract scores
but not application utility. Those mixes hold nothing that suffers from waiting, so this script
asks the question directly, on the agreed execution model:

    1. Which applications lose utility when they wait on a contended link?
    2. When those applications share the link, does the policy change their utility, and does
       the contract they declare change which policy serves them best?

The mixes and contract variations below were fixed before looking at any result.

    python scripts/paper/executed_memory.py --draws 64
"""

from __future__ import annotations

import argparse
import math
import multiprocessing
import statistics
from pathlib import Path

from qnetbench.apps import available_apps, get_app
from qnetbench.characterize.provenance import write_atomic
from qnetbench.contention import COHERENCE_TIME, LINK_FIDELITY
from qnetbench.tenancy import ExecutionModel, TenantSpec, application_utility, run_tenants
from qnetbench.topology import LinkModel

CAPACITY = 160.0
CLASSICAL_LATENCY = 1e-3
LINK = LinkModel(1.0 / CAPACITY, LINK_FIDELITY, 0.0)
POLICIES = ("fifo", "fidelity_first", "edf")
OUT = Path(__file__).parent / "data" / "executed_memory.txt"

SENSITIVE = ("dqc_qft4", "dqc_qft4", "dqc_random4")
BACKGROUND = {
    "with qkd": ("qkd", {"rounds": 256}),
    "with gates": ("distributed_gate", {"reps": 64}),
}
CONTRACTS: dict[str, dict[str, object]] = {
    "as declared": {},
    "min_fidelity 0.95": {"min_fidelity": 0.95},
    "no deadline": {"latency_budget": 1.0},  # also clears the per-layer deadline
}


def _census_cell(args: tuple[str, float, str, int]) -> tuple[str, float, str, float]:
    app, coherence, noise, seed = args
    tenants = [TenantSpec("subject", app)] + [
        TenantSpec(f"bg{i}", "qkd", {"rounds": 256}) for i in range(4)
    ]
    run = run_tenants(
        tenants,
        seed=seed,
        arbitration="policy:fifo",
        link=LINK,
        classical_latency=CLASSICAL_LATENCY,
        coherence_time=coherence,
        model=ExecutionModel(memory_noise=noise),  # type: ignore[arg-type]
    )
    return app, coherence, noise, application_utility(run.traces["subject"])


def _mix_cell(args: tuple[str, str, str, int]) -> tuple[str, str, str, int, float, float]:
    background, contract, policy, seed = args
    app, cfg = BACKGROUND[background]
    tenants = [
        TenantSpec(f"s{i}", name, demand_override=CONTRACTS[contract])
        for i, name in enumerate(SENSITIVE)
    ] + [TenantSpec(f"bg{i}", app, cfg) for i in range(2)]
    run = run_tenants(
        tenants,
        seed=seed,
        arbitration=f"policy:{policy}",
        link=LINK,
        classical_latency=CLASSICAL_LATENCY,
        coherence_time=COHERENCE_TIME,
    )
    sensitive = [application_utility(run.traces[f"s{i}"]) for i in range(len(SENSITIVE))]
    others = [application_utility(run.traces[f"bg{i}"]) for i in range(2)]
    return background, contract, policy, seed, statistics.fmean(sensitive), statistics.fmean(others)


def _census(pool: multiprocessing.pool.Pool, seeds: int) -> list[str]:
    apps = [a for a in available_apps() if len(get_app(a).roles()) == 2]
    settings = [
        (math.inf, "dephasing"),
        (COHERENCE_TIME, "dephasing"),
        (COHERENCE_TIME, "depolarizing"),
    ]
    work = [(a, c, n, s) for a in apps for c, n in settings for s in range(seeds)]
    values: dict[tuple[str, float, str], list[float]] = {}
    for app, coherence, noise, utility in pool.map(_census_cell, work):
        values.setdefault((app, coherence, noise), []).append(utility)
    lines = [
        f"1. Application utility while sharing the link with four qkd tenants, FIFO, {seeds} "
        "seeds.",
        f"   Memory coherence time {COHERENCE_TIME} s per qubit.",
        f"   {'application':24}{'no decay':>10}{'dephasing':>11}{'depolarizing':>14}",
    ]
    for app in apps:
        row = "".join(
            f"{statistics.fmean(values[(app, c, n)]):>{w}.3f}"
            for (c, n), w in zip(settings, (10, 11, 14), strict=True)
        )
        lines.append(f"   {app:24}{row}")
    return lines


def _mixes(pool: multiprocessing.pool.Pool, draws: int) -> list[str]:
    work = [
        (b, c, p, s) for b in BACKGROUND for c in CONTRACTS for p in POLICIES for s in range(draws)
    ]
    sensitive: dict[tuple[str, str, str], dict[int, float]] = {}
    others: dict[tuple[str, str, str], list[float]] = {}
    for background, contract, policy, seed, s_value, o_value in pool.map(_mix_cell, work):
        sensitive.setdefault((background, contract, policy), {})[seed] = s_value
        others.setdefault((background, contract, policy), []).append(o_value)

    lines = [
        "",
        f"2. Three sensitive tenants ({', '.join(SENSITIVE)}) and two background tenants,",
        f"   {CAPACITY:g} pairs/s, dephasing, {draws} seeds shared across policies. s.e. is "
        "across seeds.",
    ]
    for background in BACKGROUND:
        for contract in CONTRACTS:
            lines += ["", f"   {background}, dqc contract {contract}"]
            lines.append(f"     {'policy':16}{'dqc utility':>18}{'background utility':>22}")
            means = {}
            for policy in POLICIES:
                values = list(sensitive[(background, contract, policy)].values())
                means[policy] = statistics.fmean(values)
                se = statistics.stdev(values) / math.sqrt(len(values))
                other = statistics.fmean(others[(background, contract, policy)])
                cell = f"{means[policy]:.3f} ± {se:.3f}"
                lines.append(f"     {policy:16}{cell:>18}{other:>22.3f}")
            first, *rest = sorted(POLICIES, key=lambda p: -means[p])
            for other_policy in rest:
                leads = [
                    sensitive[(background, contract, first)][s]
                    - sensitive[(background, contract, other_policy)][s]
                    for s in range(draws)
                ]
                error = statistics.stdev(leads) / math.sqrt(len(leads))
                if error > 0:
                    lead = statistics.fmean(leads)
                    verdict = f"{lead:+.3f}, {lead / error:.1f} s.e. (paired)"
                else:
                    verdict = "identical on every seed"
                lines.append(f"     {first} over {other_policy}: {verdict}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--draws", type=int, default=64)
    parser.add_argument("--census-seeds", type=int, default=16)
    parser.add_argument("--jobs", type=int, default=max(1, (multiprocessing.cpu_count() or 2) - 1))
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    with multiprocessing.Pool(args.jobs) as pool:
        lines = _census(pool, args.census_seeds) + _mixes(pool, args.draws)
    text = "\n".join(lines) + "\n"
    write_atomic(args.out, text)
    print(text)


if __name__ == "__main__":
    main()
