"""Does the supply's timing move a policy's measured result, on the workload where policy matters?

Position verification sharing one link, at one link description, on each supply.

    .venv/bin/python scripts/paper/position_supplies.py reference sequence
    .venv-ns/bin/python scripts/paper/position_supplies.py netsquid netsquid-exponential
    .venv/bin/python scripts/paper/position_supplies.py --merge
"""

from __future__ import annotations

import json
import multiprocessing
import statistics
import sys
from pathlib import Path

from qnetbench.characterize.provenance import write_atomic
from qnetbench.tenancy import ExecutionModel, TenantSpec, application_utility, run_tenants
from qnetbench.topology import LinkModel

DATA = Path(__file__).parent / "data"
RATE = 153.0
SEEDS = 16
POLICIES = ("fifo", "fidelity_first", "edf")
# NetSquid's source has drawn random gaps by default since release 1.1.0. The results here were
# produced with its fixed-period source, so "netsquid" is pinned to it.
OPTIONS: dict[str, dict] = {
    "netsquid": {"timing": "fixed"},
    "netsquid-exponential": {"timing": "exponential"},
}
ORDER = ("reference", "sequence", "netsquid", "netsquid-exponential")
BACKGROUND = {
    "none": None,
    "qkd": ("qkd", "rounds", 256),
    "gates": ("distributed_gate", "reps", 128),
}


def _cell(args):
    supply, background, policy, seed = args
    tenants = [TenantSpec(f"pv{i}", "position_verification", {"rounds": 96}) for i in range(2)]
    spec = BACKGROUND[background]
    if spec is not None:
        app, key, count = spec
        tenants += [TenantSpec(f"bg{i}", app, {key: count}) for i in range(3)]
    run = run_tenants(
        tenants,
        seed=seed,
        arbitration=f"policy:{policy}",
        link=LinkModel(1.0 / RATE, 0.99, 0.0),
        classical_latency=1e-3,
        model=ExecutionModel(arrivals="closed_loop"),
        supply=supply.split("-")[0],
        supply_window=20.0,
        supply_options=OPTIONS.get(supply),
    )
    return (
        supply,
        background,
        policy,
        statistics.fmean(application_utility(run.traces[f"pv{i}"]) for i in range(2)),
        max(run.traces[f"pv{i}"][-1].t for i in range(2)),
    )


def main() -> None:
    if sys.argv[1] != "--merge":
        supplies = sys.argv[1:]
        work = [
            (s, b, p, seed)
            for s in supplies
            for b in BACKGROUND
            for p in POLICIES
            for seed in range(SEEDS)
        ]
        results: dict = {}
        with multiprocessing.Pool() as pool:
            for s, b, p, u, f in pool.map(_cell, work, chunksize=2):
                results.setdefault(s, {}).setdefault(b, {}).setdefault(p, []).append((u, f))
        (DATA / f"position_supplies_{supplies[0]}.json").write_text(json.dumps(results))
        print("wrote", supplies)
        return
    results = {}
    for path in DATA.glob("position_supplies_*.json"):
        results.update(json.loads(path.read_text()))
    lines = [
        f"Two position_verification tenants and three background tenants, {RATE:g} pairs/s, {SEEDS} seeds.",
        "Verifier utility, then finish time (s), under FIFO / fidelity-first / EDF.",
        "",
        f"{'supply':24}{'background':>12}{'utility':>24}{'finish time':>24}",
    ]
    for supply in [s for s in ORDER if s in results]:
        for background in BACKGROUND:
            cells = results[supply][background]
            u = " ".join(f"{statistics.fmean(x[0] for x in cells[p]):.3f}" for p in POLICIES)
            f = " ".join(f"{statistics.fmean(x[1] for x in cells[p]):6.2f}" for p in POLICIES)
            lines.append(f"{supply:24}{background:>12}{u:>24}{f:>24}")
    text = "\n".join(lines) + "\n"
    write_atomic(DATA / "position_supplies.txt", text)
    print(text)


if __name__ == "__main__":
    main()
