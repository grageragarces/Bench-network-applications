"""A natural workload where the scheduler decides what the application achieves.

Position verification counts a round only if its pair met a deadline set by physics, so a late pair
is a failed verification, with or without memory noise. So this is the direct test of whether a policy
changes measured utility, and whether the workload and contract change which policy serves it best.

A blocked tenant loses only one round while it is starved, and then runs the rest alone once the
background has finished, so utility alone rewards postponing a whole job. Finish time is reported beside
it, with a no-background baseline and a background four times longer to expose that effect.

The mixes and contract variations were fixed before looking at any result.

    python scripts/paper/position_mix.py
"""

from __future__ import annotations

import math
import multiprocessing
import statistics
from pathlib import Path

from qnetbench.characterize.provenance import write_atomic
from qnetbench.tenancy import ExecutionModel, TenantSpec, application_utility, run_tenants
from qnetbench.topology import LinkModel

OUT = Path(__file__).parent / "data" / "position_mix.txt"
POLICIES = ("fifo", "fidelity_first", "edf")
SEEDS = 64
BACKGROUND = {
    "none": None,
    "qkd": ("qkd", "rounds", 256),
    "chsh": ("chsh", "rounds", 256),
    "gates": ("distributed_gate", "reps", 128),
    "bqc": ("bqc", "depth", 128),
}
CONTRACTS: dict[str, dict[str, object]] = {
    "as declared": {},
    "min_fidelity 0.95": {"min_fidelity": 0.95},
}
CAPACITIES = (100.0, 160.0, 240.0, 400.0)
LENGTHS = (1, 4)
TIMES = (math.inf, 1.0, 0.25, 0.05, 0.01, 0.005)


def _memory(args):
    """Utility against coherence time, because a verifier holds its qubit for about 2 ms."""
    coherence, background, policy, seed = args
    app, key, count = BACKGROUND[background]
    tenants = [
        TenantSpec(f"pv{i}", "position_verification", {"rounds": 96}) for i in range(2)
    ] + [TenantSpec(f"bg{i}", app, {key: count}) for i in range(3)]
    run = run_tenants(
        tenants,
        seed=seed,
        arbitration=f"policy:{policy}",
        link=LinkModel(1.0 / 160, 0.99, 0.0),
        classical_latency=1e-3,
        coherence_time=coherence,
        model=ExecutionModel(arrivals="closed_loop"),
    )
    return args, statistics.fmean(application_utility(run.traces[f"pv{i}"]) for i in range(2))


def _cell(args):
    capacity, length, background, contract, policy, seed = args
    tenants = [
        TenantSpec(
            f"pv{i}",
            "position_verification",
            {"rounds": 96},
            demand_override=CONTRACTS[contract],
        )
        for i in range(2)
    ]
    spec = BACKGROUND[background]
    if spec is not None:
        app, key, count = spec
        tenants += [TenantSpec(f"bg{i}", app, {key: count * length}) for i in range(3)]
    run = run_tenants(
        tenants,
        seed=seed,
        arbitration=f"policy:{policy}",
        link=LinkModel(1.0 / capacity, 0.99, 0.0),
        classical_latency=1e-3,
        model=ExecutionModel(arrivals="closed_loop"),
    )
    return args, (
        statistics.fmean(application_utility(run.traces[f"pv{i}"]) for i in range(2)),
        max(run.traces[f"pv{i}"][-1].t for i in range(2)),
    )


def _rows(results, capacity, length, background, contract):
    utility = {}
    finish = {}
    for policy in POLICIES:
        keys = [(capacity, length, background, contract, policy, s) for s in range(SEEDS)]
        utility[policy] = [results[k][0] for k in keys]
        finish[policy] = [results[k][1] for k in keys]
    return utility, finish


def main() -> None:
    work = [
        (c, n, b, k, p, s)
        for c in CAPACITIES
        for n in LENGTHS
        for b in BACKGROUND
        for k in CONTRACTS
        for p in POLICIES
        for s in range(SEEDS)
        if not (b == "none" and n != 1)
    ]
    with multiprocessing.Pool() as pool:
        results = dict(pool.map(_cell, work, chunksize=8))
        memory = dict(
            pool.map(
                _memory,
                [
                    (t, b, p, s)
                    for t in TIMES
                    for b in ("qkd", "gates")
                    for p in POLICIES
                    for s in range(SEEDS)
                ],
                chunksize=8,
            )
        )

    lines = [
        "Two position_verification tenants (96 rounds, 10 ms bound) and three background tenants,",
        f"{SEEDS} seeds, closed loop, no memory decay, link fidelity 0.99, classical delay 1 ms.",
        "Verifier utility and verifier finish time (s) under FIFO / fidelity-first / EDF.",
        "",
        f"{'pairs/s':>8}{'bg x':>5}{'background':>12}{'contract':>19}"
        f"{'utility':>24}{'finish time':>24}{'best utility':>17}{'over next':>20}",
    ]
    for c in CAPACITIES:
        for n in LENGTHS:
            for b in BACKGROUND:
                if b == "none" and n != 1:
                    continue
                for k in CONTRACTS:
                    utility, finish = _rows(results, c, n, b, k)
                    u = {p: statistics.fmean(v) for p, v in utility.items()}
                    f = {p: statistics.fmean(v) for p, v in finish.items()}
                    first, second, _ = sorted(POLICIES, key=lambda p: -u[p])
                    diff = [x - y for x, y in zip(utility[first], utility[second], strict=True)]
                    se = statistics.stdev(diff) / math.sqrt(SEEDS)
                    note = (
                        f"{statistics.fmean(diff):+.3f} ({statistics.fmean(diff) / se:.1f} s.e.)"
                        if se > 0
                        else "tied"
                    )
                    us = " ".join(f"{u[p]:.3f}" for p in POLICIES)
                    fs = " ".join(f"{f[p]:6.2f}" for p in POLICIES)
                    lines.append(
                        f"{c:>8g}{n:>5}{b:>12}{k:>19}{us:>24}{fs:>24}{first:>17}{note:>20}"
                    )
    lines += [
        "",
        "Verifier utility against coherence time, 160 pairs/s, as declared, FIFO / fidelity-first / EDF.",
        f"{'T2 (s)':>8}{'with qkd':>24}{'with gates':>24}",
    ]
    for coherence in TIMES:
        cells = [
            " ".join(
                f"{statistics.fmean(memory[(coherence, b, p, s)] for s in range(SEEDS)):.3f}"
                for p in POLICIES
            )
            for b in ("qkd", "gates")
        ]
        lines.append(f"{coherence:>8g}{cells[0]:>24}{cells[1]:>24}")
    text = "\n".join(lines) + "\n"
    write_atomic(OUT, text)
    print(text)


if __name__ == "__main__":
    main()
