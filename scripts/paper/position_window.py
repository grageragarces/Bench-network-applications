"""Position verification against the length of its timing window, by policy.

The verifier asks for a pair and commits to issuing its challenge a fixed window later, so the
prover's half must arrive inside that window. A half that arrived much earlier could be forwarded by
an attacker to wherever the classical challenge arrives first, and one that arrives later makes the
honest answer late, so the window is a protocol parameter rather than a constant of nature. This
sweeps it, to show over what range the scheduler decides what the application achieves.

    python scripts/paper/position_window.py
"""

from __future__ import annotations

import math
import multiprocessing
import statistics
from pathlib import Path

from qnetbench.characterize.provenance import write_atomic
from qnetbench.tenancy import ExecutionModel, TenantSpec, application_utility, run_tenants
from qnetbench.topology import LinkModel

OUT = Path(__file__).parent / "data" / "position_window.txt"
POLICIES = ("fifo", "fidelity_first", "edf")
SEEDS = 64
CAPACITY = 160.0
WINDOWS = (0.005, 0.010, 0.020, 0.050, 0.100)
BACKGROUND = {
    "none": None,
    "qkd": ("qkd", "rounds", 256),
    "gates": ("distributed_gate", "reps", 128),
}


def _cell(args):
    window, background, policy, seed = args
    tenants = [
        TenantSpec(f"pv{i}", "position_verification", {"rounds": 96, "response_budget": window})
        for i in range(2)
    ]
    spec = BACKGROUND[background]
    if spec is not None:
        app, key, count = spec
        tenants += [TenantSpec(f"bg{i}", app, {key: count}) for i in range(3)]
    run = run_tenants(
        tenants,
        seed=seed,
        arbitration=f"policy:{policy}",
        link=LinkModel(1.0 / CAPACITY, 0.99, 0.0),
        classical_latency=1e-3,
        model=ExecutionModel(arrivals="closed_loop"),
    )
    return args, (
        statistics.fmean(application_utility(run.traces[f"pv{i}"]) for i in range(2)),
        max(run.traces[f"pv{i}"][-1].t for i in range(2)),
    )


def main() -> None:
    work = [
        (w, b, p, s) for w in WINDOWS for b in BACKGROUND for p in POLICIES for s in range(SEEDS)
    ]
    with multiprocessing.Pool() as pool:
        results = dict(pool.map(_cell, work, chunksize=8))

    lines = [
        "Two position_verification tenants (96 rounds) and three background tenants, by timing "
        "window,",
        f"{CAPACITY:g} pairs/s, {SEEDS} seeds, closed loop, no memory decay, link fidelity 0.99, "
        "classical delay 1 ms, contracts as declared.",
        "Verifier utility and verifier finish time (s) under FIFO / fidelity-first / EDF.",
        "",
        f"{'window (ms)':>12}{'background':>12}{'utility':>24}{'finish time':>24}"
        f"{'EDF - FIFO':>22}  {'best utility'}",
    ]
    for w in WINDOWS:
        for b in BACKGROUND:
            utility = {p: [results[(w, b, p, s)][0] for s in range(SEEDS)] for p in POLICIES}
            finish = {p: [results[(w, b, p, s)][1] for s in range(SEEDS)] for p in POLICIES}
            u = {p: statistics.fmean(v) for p, v in utility.items()}
            f = {p: statistics.fmean(v) for p, v in finish.items()}
            diff = [e - q for e, q in zip(utility["edf"], utility["fifo"], strict=True)]
            se = statistics.stdev(diff) / math.sqrt(SEEDS)
            gap = (
                f"{statistics.fmean(diff):+.3f} ({statistics.fmean(diff) / se:.1f} s.e.)"
                if se > 0
                else "tied"
            )
            top = max(u.values())
            best = "/".join(p for p in POLICIES if u[p] == top)
            us = " ".join(f"{u[p]:.3f}" for p in POLICIES)
            fs = " ".join(f"{f[p]:6.2f}" for p in POLICIES)
            lines.append(f"{w * 1e3:>12g}{b:>12}{us:>24}{fs:>24}{gap:>22}  {best}")
    text = "\n".join(lines) + "\n"
    write_atomic(OUT, text)
    print(text)


if __name__ == "__main__":
    main()
