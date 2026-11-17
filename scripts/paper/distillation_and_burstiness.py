"""Distillation and burstiness on running applications.

A queue model cannot express distillation's demand: it scores a binary contract, which a
distillation tenant meets the moment it is served. Execution
can express it, because the first pair of a recurrence step really does wait in memory while the
second is generated, and sharing the link lengthens that wait. So this asks whether the mix the
queue model cannot score responds to the policy once the applications run.

Then burstiness. In the queue model the bursty mix meets fewer contracts at every resolvable
capacity. That comes from its open-loop arrivals, so it is checked with applications that block.

    python scripts/paper/distillation_and_burstiness.py
"""

from __future__ import annotations

import math
import multiprocessing
import statistics
from pathlib import Path

from qnetbench.characterize.provenance import write_atomic
from qnetbench.contention import LINK_FIDELITY, arrival_times, burstiness_mixes, simulate
from qnetbench.metrics.report import compute_report
from qnetbench.policies import get_policy
from qnetbench.tenancy import (
    ExecutionModel,
    TenantSpec,
    application_utility,
    contract_satisfaction,
    run_tenants,
)
from qnetbench.topology import LinkModel
from qnetbench.trace.events import AppOutcomeEvent

OUT = Path(__file__).parent / "data" / "distillation_and_burstiness.txt"
POLICIES = ("fifo", "fidelity_first", "edf")
LINK = LinkModel(1.0 / 160, LINK_FIDELITY, 0.0)
TIMES = (0.05, 0.25, 1.0, math.inf)
UNITS = ("pair", "request")


def _distillation(args: tuple[float, str, str, int]) -> tuple[tuple[float, str, str, int], dict]:
    coherence, unit, policy, seed = args
    tenants = [
        TenantSpec(f"d{i}", "distillation", {"rounds": 24, "control_rounds": 12}) for i in range(4)
    ] + [TenantSpec("q", "qkd", {"rounds": 256})]
    run = run_tenants(
        tenants,
        seed=seed,
        arbitration=f"policy:{policy}",
        link=LINK,
        classical_latency=1e-3,
        coherence_time=coherence,
        model=ExecutionModel(arrivals="closed_loop", service_unit=unit),
    )
    distilled = []
    pair_yield = []
    for i in range(4):
        outcome = next(e for e in run.traces[f"d{i}"] if isinstance(e, AppOutcomeEvent))
        distilled.append(float(outcome.payload["distilled_quality"]))
        pair_yield.append(float(outcome.payload["yield"]))
    return args, {
        "fidelity": statistics.fmean(distilled),
        "yield": statistics.fmean(pair_yield),
        "satisfaction": statistics.fmean(
            contract_satisfaction(run.traces[f"d{i}"], ignore=()) for i in range(4)
        ),
        "qkd": application_utility(run.traces["q"]),
        "finish": max(run.traces[f"d{i}"][-1].t for i in range(4)),
    }


def _bursty(args: tuple[str, float, int]) -> tuple[tuple[str, float, int], tuple[float, ...]]:
    shape, capacity, seed = args
    tenants = burstiness_mixes("heralded_teleport", count=5, n_requests=100, seed=seed)[shape]
    model_value = simulate(
        tenants,
        get_policy("fifo"),
        capacity=capacity,
        link_fidelity=LINK_FIDELITY,
        coherence_time=0.25,
    ).aggregate_utility
    specs = [
        TenantSpec(f"h{i}", t.app, {"sessions": 40}, tuple(arrival_times(t)))
        for i, t in enumerate(tenants)
    ]
    run = run_tenants(
        specs,
        seed=seed,
        arbitration="policy:fifo",
        link=LinkModel(1.0 / capacity, LINK_FIDELITY, 0.0),
        classical_latency=1e-3,
        coherence_time=0.25,
    )
    executed = statistics.fmean(contract_satisfaction(run.traces[s.name]) for s in specs)
    reports = [compute_report(run.traces[s.name]) for s in specs]
    mean_ms = statistics.fmean(r.latency_mean for r in reports) * 1e3
    p95_ms = statistics.fmean(r.latency_p95 for r in reports) * 1e3
    return args, (model_value, executed, mean_ms, p95_ms)


def main() -> None:
    seeds = 32
    with multiprocessing.Pool() as pool:
        distillation = dict(
            pool.map(
                _distillation,
                [
                    (c, u, p, s)
                    for c in TIMES
                    for u in UNITS
                    for p in POLICIES
                    for s in range(seeds)
                ],
            )
        )
        capacities = (140.0, 160.0, 180.0, 220.0, 300.0)
        bursty = dict(
            pool.map(
                _bursty,
                [
                    (shape, c, s)
                    for shape in ("bursty", "smooth")
                    for c in capacities
                    for s in range(16)
                ],
            )
        )

    lines = [
        f"1. Four distillation tenants and one qkd tenant, 160 pairs/s, {seeds} seeds, closed loop.",
        "   Output fidelity is what the application measured. Satisfaction includes staleness.",
        "",
        f"   {'T2 (s)':>7}{'unit':>9}{'policy':>16}{'output F':>10}{'s.e.':>8}{'yield':>8}"
        f"{'satisf.':>9}{'qkd util':>10}{'finish s':>10}",
    ]
    for c in TIMES:
        for unit in UNITS:
            for policy in POLICIES:
                rows = [distillation[(c, unit, policy, s)] for s in range(seeds)]
                values = [r["fidelity"] for r in rows]
                se = statistics.stdev(values) / math.sqrt(seeds)
                lines.append(
                    f"   {c:>7g}{unit:>9}{policy:>16}{statistics.fmean(values):>10.3f}{se:>8.3f}"
                    f"{statistics.fmean(r['yield'] for r in rows):>8.3f}"
                    f"{statistics.fmean(r['satisfaction'] for r in rows):>9.3f}"
                    f"{statistics.fmean(r['qkd'] for r in rows):>10.3f}"
                    f"{statistics.fmean(r['finish'] for r in rows):>10.3f}"
                )
    lines += [
        "",
        "2. Burstiness: five heralded_teleport tenants, FIFO, 16 draws. Its contract has no deadline",
        "   and pairs are fresh on the agreed model, so satisfaction cannot fall when it runs. Latency",
        "   is what can still show whether bursts matter. Latency in ms, bursty / smooth.",
        f"   {'pairs/s':>8}{'model bursty':>14}{'model smooth':>14}{'run bursty':>12}{'run smooth':>12}"
        f"{'mean latency':>16}{'p95 latency':>16}",
    ]
    for c in capacities:
        cells = []
        for index in (0, 1, 2, 3):
            for shape in ("bursty", "smooth"):
                cells.append(statistics.fmean(bursty[(shape, c, s)][index] for s in range(16)))
        lines.append(
            f"   {c:>8g}{cells[0]:>14.3f}{cells[1]:>14.3f}{cells[2]:>12.3f}{cells[3]:>12.3f}"
            f"{f'{cells[4]:.1f} / {cells[5]:.1f}':>16}{f'{cells[6]:.1f} / {cells[7]:.1f}':>16}"
        )
    lines += [
        "",
        "3. Paired differences on the distillation mix: fidelity-first minus FIFO, pair by pair.",
        f"   {'T2 (s)':>7}{'yield':>18}{'output F':>18}{'finish (s)':>18}",
    ]
    for c in TIMES:
        cells = []
        for key in ("yield", "fidelity", "finish"):
            diff = [
                distillation[(c, "pair", "fidelity_first", s)][key]
                - distillation[(c, "pair", "fifo", s)][key]
                for s in range(seeds)
            ]
            se = statistics.stdev(diff) / math.sqrt(seeds)
            cells.append(f"{statistics.fmean(diff):+.3f} ± {se:.3f}")
        lines.append(f"   {c:>7g}{cells[0]:>18}{cells[1]:>18}{cells[2]:>18}")
    text = "\n".join(lines) + "\n"
    write_atomic(OUT, text)
    print(text)


if __name__ == "__main__":
    main()
