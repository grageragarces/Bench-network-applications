"""Does any contract or operating point make the default mixes disagree on the agreed model?

Fixes the execution model and varies what the queue-model table left fixed: every tenant's fidelity
margin and deadline budget, the link's capacity and fidelity, and which metric picks the winner.
A cell "disagrees" if, in most draws, no policy is tied for best on both mixes.

    python scripts/paper/sensitivity_map.py
"""

from __future__ import annotations

import multiprocessing
import statistics
from pathlib import Path

from qnetbench.characterize.provenance import write_atomic
from qnetbench.contention import (
    COHERENCE_TIME,
    ContentionResult,
    Tenant,
    arrival_times,
    default_mixes,
    has_inversion,
)
from qnetbench.tenancy import (
    TenantSpec,
    application_utility,
    contract_satisfaction,
    run_tenants,
)
from qnetbench.topology import LinkModel

OUT = Path(__file__).parent / "data" / "sensitivity_map.txt"
POLICIES = ("fifo", "fidelity_first", "edf")
MIXES = ("deadline_heavy", "fidelity_heavy")
MARGINS = (-0.05, 0.0, 0.03)
BUDGETS = (0.25, 0.5, 1.0, 2.0)
CAPACITIES = (100.0, 160.0, 240.0)
LINK_FIDELITIES = (0.99, 0.93)
DRAWS = 8
REQUEST_COUNT = {"distributed_gate": "reps", "qkd": "rounds", "bqc": "depth", "chsh": "rounds"}
METRICS = ("satisfaction", "worst served", "utility")


def _override(tenant: Tenant, margin: float, budget_scale: float) -> dict[str, object]:
    fields: dict[str, object] = {"min_fidelity": min(1.0, max(0.0, tenant.min_fidelity + margin))}
    if tenant.budget is not None:
        fields["latency_budget"] = tenant.budget * budget_scale
    return fields


def _cell(args):
    margin, budget, capacity, link_fidelity, mix, policy, draw = args
    tenants = default_mixes(100, seed=draw)[mix]
    specs = [
        TenantSpec(
            f"{t.app}-{i}",
            t.app,
            {REQUEST_COUNT[t.app]: t.n_requests},
            tuple(arrival_times(t)),
            demand_override=_override(t, margin, budget),
        )
        for i, t in enumerate(tenants)
    ]
    run = run_tenants(
        specs,
        seed=draw,
        arbitration=f"policy:{policy}",
        link=LINK(capacity, link_fidelity),
        classical_latency=1e-3,
        coherence_time=COHERENCE_TIME,
    )
    satisfaction = [contract_satisfaction(run.traces[s.name]) for s in specs]
    by_app: dict[str, list[float]] = {}
    for spec, value in zip(specs, satisfaction, strict=True):
        by_app.setdefault(spec.app, []).append(value)
    return args, {
        "satisfaction": statistics.fmean(satisfaction),
        "worst served": min(statistics.fmean(v) for v in by_app.values()),
        "utility": statistics.fmean(application_utility(run.traces[s.name]) for s in specs),
    }


def LINK(capacity: float, link_fidelity: float) -> LinkModel:  # noqa: N802
    return LinkModel(1.0 / capacity, link_fidelity, 0.0)


def main() -> None:
    work = [
        (m, b, c, f, mix, p, d)
        for m in MARGINS
        for b in BUDGETS
        for c in CAPACITIES
        for f in LINK_FIDELITIES
        for mix in MIXES
        for p in POLICIES
        for d in range(DRAWS)
    ]
    with multiprocessing.Pool() as pool:
        results = dict(pool.map(_cell, work, chunksize=8))

    lines = [
        f"Agreed model, {DRAWS} draws per cell, dephasing at {COHERENCE_TIME} s. Fidelity margin is "
        "added to every declared min_fidelity,",
        "budget scale multiplies every deadline budget. Winner lists the policies tied for best at "
        "3 places.",
        "",
        f"{'margin':>7}{'budget':>7}{'pairs/s':>8}{'link F':>7}  {'metric':13}"
        f"{'deadline-heavy':>22}{'fidelity-heavy':>22}{'disagree':>10}",
    ]
    short = {"fifo": "F", "fidelity_first": "Q", "edf": "E"}
    totals = {metric: [0, 0] for metric in METRICS}
    disagreeing_cells: list[str] = []
    for m in MARGINS:
        for b in BUDGETS:
            for c in CAPACITIES:
                for f in LINK_FIDELITIES:
                    for metric in METRICS:
                        winners = {}
                        for mix in MIXES:
                            means = {
                                p: statistics.fmean(
                                    results[(m, b, c, f, mix, p, d)][metric] for d in range(DRAWS)
                                )
                                for p in POLICIES
                            }
                            top = max(means.values())
                            names = "".join(
                                short[p] for p in POLICIES if round(means[p], 3) == round(top, 3)
                            )
                            winners[mix] = f"{names} {top:.3f}"
                        count = 0
                        for d in range(DRAWS):
                            table = {
                                mix: {
                                    p: ContentionResult(
                                        policy=p,
                                        aggregate_utility=round(
                                            results[(m, b, c, f, mix, p, d)][metric], 9
                                        ),
                                    )
                                    for p in POLICIES
                                }
                                for mix in MIXES
                            }
                            count += has_inversion(table)
                        totals[metric][0] += 1
                        if count > DRAWS / 2:
                            totals[metric][1] += 1
                            disagreeing_cells.append(
                                f"margin {m:+.2f}, budget x{b:g}, {c:g} pairs/s, link F {f}, {metric}"
                            )
                        lines.append(
                            f"{m:>+7.2f}{b:>7g}{c:>8g}{f:>7g}  {metric:13}"
                            f"{winners['deadline_heavy']:>22}{winners['fidelity_heavy']:>22}"
                            f"{count:>7}/{DRAWS}"
                        )
    summary = ["", "F = FIFO, Q = fidelity-first, E = EDF.", "", "Cells where most draws disagree:"]
    for metric, (total, hits) in totals.items():
        summary.append(f"  {metric:14}{hits:>4} of {total}")
    if disagreeing_cells:
        summary += ["", *disagreeing_cells]
    text = "\n".join(lines + summary) + "\n"
    write_atomic(OUT, text)
    print("\n".join(summary))


if __name__ == "__main__":
    main()
