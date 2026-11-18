"""Scheduling results with contracts set from measurement instead of by hand.

Every contract in the suite is declared by hand in the application's code, and the declared
`min_fidelity` does not track the fidelity at which an application loses half its utility
(`contract_provenance.py`). This replaces each tenant's declared `min_fidelity` with its measured
fidelity threshold F_1/2 from the characterization data, keeps every other contract field, and
reruns the two scheduling results the conclusions rest on:

1. the two default mixes on the default execution model (blocking applications, on-demand
   service, held qubits decay), scored on contract satisfaction, worst-served application and
   utility;
2. two position_verification tenants beside three background tenants.

The "declared" rows reproduce the published results, so any difference is the contracts.

    python scripts/paper/measured_contracts.py
"""

from __future__ import annotations

import json
import math
import multiprocessing
import statistics
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from executed_contention import (  # noqa: E402
    CLASSICAL_LATENCY,
    POLICIES,
    _specs,
)

from qnetbench.characterize.provenance import write_atomic  # noqa: E402
from qnetbench.contention import (  # noqa: E402
    CAPACITY,
    COHERENCE_TIME,
    DRAWS,
    LINK_FIDELITY,
    N_REQUESTS,
    ContentionResult,
    default_mixes,
    has_inversion,
)
from qnetbench.tenancy import (  # noqa: E402
    ExecutionModel,
    TenantSpec,
    application_utility,
    contract_satisfaction,
    run_tenants,
)
from qnetbench.topology import LinkModel  # noqa: E402

DATA = Path(__file__).parent / "data"
OUT = DATA / "measured_contracts.txt"
CONTRACTS = ("declared", "measured")
PV_SEEDS = 64
PV_CAPACITY = 160.0
PV_BACKGROUND = {
    "qkd": ("qkd", "rounds", 256),
    "gates": ("distributed_gate", "reps", 128),
    "bqc": ("bqc", "depth", 128),
}


def threshold(app: str) -> float:
    """The measured fidelity at which `app` reaches the midpoint of its utility range."""
    data = json.loads((DATA / f"{app}.json").read_text())
    return float(data["signature"]["fidelity_threshold"])


def _override(spec: TenantSpec, contract: str) -> TenantSpec:
    if contract == "declared":
        return spec
    return replace(spec, demand_override={"min_fidelity": threshold(spec.app)})


def _mix(args: tuple[int, str, str, str]) -> tuple[tuple[int, str, str, str], tuple]:
    draw, mix, contract, policy = args
    tenants = default_mixes(N_REQUESTS, seed=draw)[mix]
    specs = [_override(s, contract) for s in _specs(tenants, open_loop=False)]
    run = run_tenants(
        specs,
        seed=draw,
        arbitration=f"policy:{policy}",
        link=LinkModel(1.0 / CAPACITY, LINK_FIDELITY, 0.0),
        classical_latency=CLASSICAL_LATENCY,
        coherence_time=COHERENCE_TIME,
        model=ExecutionModel(),
    )
    satisfaction: dict[str, list[float]] = {}
    utility: dict[str, list[float]] = {}
    for s in specs:
        satisfaction.setdefault(s.app, []).append(contract_satisfaction(run.traces[s.name]))
        utility.setdefault(s.app, []).append(application_utility(run.traces[s.name]))
    every = [contract_satisfaction(run.traces[s.name]) for s in specs]
    return args, (
        statistics.fmean(every),
        min(statistics.fmean(v) for v in satisfaction.values()),
        statistics.fmean(statistics.fmean(v) for v in utility.values()),
    )


def _pv(args: tuple[str, str, str, int]) -> tuple[tuple[str, str, str, int], tuple]:
    background, contract, policy, seed = args
    app, key, count = PV_BACKGROUND[background]
    tenants = [TenantSpec(f"pv{i}", "position_verification", {"rounds": 96}) for i in range(2)] + [
        TenantSpec(f"bg{i}", app, {key: count}) for i in range(3)
    ]
    tenants = [_override(t, contract) for t in tenants]
    run = run_tenants(
        tenants,
        seed=seed,
        arbitration=f"policy:{policy}",
        link=LinkModel(1.0 / PV_CAPACITY, 0.99, 0.0),
        classical_latency=1e-3,
        model=ExecutionModel(arrivals="closed_loop"),
    )
    return args, (
        statistics.fmean(application_utility(run.traces[f"pv{i}"]) for i in range(2)),
        max(run.traces[f"pv{i}"][-1].t for i in range(2)),
    )


def _disagree(draw: int, contract: str, results: dict) -> bool:
    by_mix = {
        mix: [
            ContentionResult(
                policy=p, aggregate_utility=round(results[(draw, mix, contract, p)][0], 9)
            )
            for p in POLICIES
        ]
        for mix in ("deadline_heavy", "fidelity_heavy")
    }
    return has_inversion({m: {r.policy: r for r in rs} for m, rs in by_mix.items()})


def main() -> None:
    mixes = ("deadline_heavy", "fidelity_heavy")
    mix_work = [
        (d, m, c, p) for d in range(DRAWS) for m in mixes for c in CONTRACTS for p in POLICIES
    ]
    pv_work = [
        (b, c, p, s)
        for b in PV_BACKGROUND
        for c in CONTRACTS
        for p in POLICIES
        for s in range(PV_SEEDS)
    ]
    with multiprocessing.Pool() as pool:
        mix = dict(pool.map(_mix, mix_work, chunksize=4))
        pv = dict(pool.map(_pv, pv_work, chunksize=8))

    apps = sorted({t.app for m in default_mixes(N_REQUESTS, seed=0).values() for t in m})
    apps = sorted(set(apps) | {"position_verification"} | {v[0] for v in PV_BACKGROUND.values()})
    lines = [
        "Measured contracts: each tenant's min_fidelity is replaced by its F_1/2 from the",
        "characterization data. Deadlines and every other field stay as declared.",
        "",
        f"{'application':24}{'declared':>10}{'measured F_1/2':>16}",
    ]
    for app in apps:
        declared = _declared(app)
        lines.append(f"{app:24}{declared:>10}{threshold(app):>16.3f}")

    lines += [
        "",
        f"1. Default mixes, default execution model, {CAPACITY:g} pairs/s, {DRAWS} draws.",
        "   FIFO / fidelity-first / EDF. Utility is the mean over applications.",
    ]
    for name, index in (("satisfaction", 0), ("worst served", 1), ("utility", 2)):
        lines.append(f"   {name}")
        for m in mixes:
            for c in CONTRACTS:
                row = " ".join(
                    f"{statistics.fmean(mix[(d, m, c, p)][index] for d in range(DRAWS)):.3f}"
                    for p in POLICIES
                )
                lines.append(f"     {m:16}{c:>10}   {row}")
    for c in CONTRACTS:
        count = sum(_disagree(d, c, mix) for d in range(DRAWS))
        lines.append(f"   draws with no policy best on both mixes, {c}: {count} of {DRAWS}")

    lines += [
        "",
        f"2. Two position_verification tenants beside three background tenants, {PV_CAPACITY:g} "
        f"pairs/s, {PV_SEEDS} seeds, no memory decay.",
        "   Verifier utility and finish time (s), FIFO / fidelity-first / EDF.",
    ]
    for b in PV_BACKGROUND:
        for c in CONTRACTS:
            u = {p: [pv[(b, c, p, s)][0] for s in range(PV_SEEDS)] for p in POLICIES}
            f = {
                p: statistics.fmean(pv[(b, c, p, s)][1] for s in range(PV_SEEDS)) for p in POLICIES
            }
            diff = [e - q for e, q in zip(u["edf"], u["fifo"], strict=True)]
            se = statistics.stdev(diff) / math.sqrt(PV_SEEDS)
            gap = (
                f"{statistics.fmean(diff):+.3f} ({statistics.fmean(diff) / se:.1f} s.e.)"
                if se
                else "tied"
            )
            us = " ".join(f"{statistics.fmean(v):.3f}" for v in u.values())
            fs = " ".join(f"{v:6.2f}" for v in f.values())
            lines.append(f"     {b:8}{c:>10}   {us}   {fs}   EDF - FIFO {gap}")
    text = "\n".join(lines) + "\n"
    write_atomic(OUT, text)
    print(text)


def _declared(app: str) -> str:
    from qnetbench.apps import get_app

    value = getattr(get_app(app), "min_fidelity", None)
    return "none" if value is None else f"{value:g}"


if __name__ == "__main__":
    main()
