"""Entanglement-based QKD on every supply at one link description.

Every supply gets the same rate, fidelity and classical delay, so a difference between columns is a
difference between supplies. Run instead at each adapter's defaults (the reference supply at 1 ms,
SeQUeNCe with 50 memories, NetSquid at 2000 pairs/s), most of what such a comparison shows comes from
those settings.

    .venv/bin/python scripts/paper/one_link_description.py reference sequence
    .venv-ns/bin/python scripts/paper/one_link_description.py netsquid netsquid-exponential
    .venv/bin/python scripts/paper/one_link_description.py --merge
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

from qnetbench.characterize.provenance import write_atomic
from qnetbench.metrics.report import compute_report
from qnetbench.tenancy import ExecutionModel, TenantSpec, run_tenants
from qnetbench.topology import LinkModel
from qnetbench.trace.events import EntanglementDelivered

DATA = Path(__file__).parent / "data"
RATE = 153.0
# NetSquid's source has drawn random gaps by default since release 1.1.0. The results here were
# produced with its fixed-period source, so "netsquid" is pinned to it.
OPTIONS: dict[str, dict] = {
    "netsquid": {"timing": "fixed"},
    "netsquid-exponential": {"timing": "exponential"},
}
ORDER = ("reference", "sequence", "netsquid", "netsquid-exponential")
SEEDS = 16


def measure(supply: str) -> dict[str, float]:
    rows = []
    for seed in range(SEEDS):
        run = run_tenants(
            [TenantSpec("t", "qkd")],
            seed=seed,
            link=LinkModel(1.0 / RATE, 0.95, 0.0),
            classical_latency=1e-3,
            model=ExecutionModel(arrivals="closed_loop", aging="none"),
            supply=supply.split("-")[0],
            supply_window=6.0,
            supply_options=OPTIONS.get(supply),
        )
        trace = run.traces["t"]
        report = compute_report(trace)
        times = [e.latency for e in trace if isinstance(e, EntanglementDelivered)]
        rows.append(
            {
                "pairs": report.n_delivered,
                "rate": report.delivered_rate,
                "fidelity": report.mean_fidelity,
                "p50": report.latency_p50 * 1e3,
                "mean": report.latency_mean * 1e3,
                "ratio": report.latency_mean / report.latency_p50,
                "cv": statistics.stdev(times) / statistics.fmean(times),
                "messages": report.msgs_per_pair,
                "utility": report.app_utility,
            }
        )
    return {k: statistics.fmean(r[k] for r in rows) for k in rows[0]}


def main() -> None:
    if sys.argv[1] != "--merge":
        results = {supply: measure(supply) for supply in sys.argv[1:]}
        (DATA / f"one_link_description_{sys.argv[1]}.json").write_text(json.dumps(results))
        print("wrote", sys.argv[1:])
        return
    results = {}
    for path in DATA.glob("one_link_description_*.json"):
        results.update(json.loads(path.read_text()))
    supplies = [s for s in ORDER if s in results]
    labels = {
        "pairs": ("Pairs delivered", "{:.0f}"),
        "rate": ("Delivered rate (pairs/s)", "{:.1f}"),
        "fidelity": ("Mean fidelity", "{:.4f}"),
        "p50": ("Latency p50 (ms)", "{:.2f}"),
        "mean": ("Latency mean (ms)", "{:.2f}"),
        "ratio": ("mean / p50", "{:.2f}"),
        "cv": ("Latency cv", "{:.2f}"),
        "messages": ("Messages per pair", "{:.4f}"),
        "utility": ("Secure key fraction", "{:.4f}"),
    }
    lines = [
        f"QKD, one link description: {RATE:g} pairs/s, F 0.95, classical delay 1 ms, {SEEDS} seeds.",
        "",
        f"{'':26}" + "".join(f"{s[:13]:>15}" for s in supplies),
    ]
    for key, (label, fmt) in labels.items():
        lines.append(f"{label:26}" + "".join(f"{fmt.format(results[s][key]):>15}" for s in supplies))
    text = "\n".join(lines) + "\n"
    write_atomic(DATA / "one_link_description.txt", text)
    print(text)


if __name__ == "__main__":
    main()
