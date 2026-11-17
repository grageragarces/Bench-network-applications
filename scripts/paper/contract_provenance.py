"""Where does each application's declared contract come from, and does it track measurement?

Reads each application's real requests from a run, its constructor defaults from its code, and its
measured fidelity threshold from the published characterization data. Writes the table to
`scripts/paper/data/contract_provenance.md`.

    python scripts/paper/contract_provenance.py
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from qnetbench.apps import available_apps, get_app
from qnetbench.characterize.provenance import write_atomic
from qnetbench.harness.runner import run_once
from qnetbench.trace.events import EntanglementRequested, QubitSent

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "scripts/paper/data"
OUT = ROOT / "scripts/paper/data/contract_provenance.md"


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0
        i = j + 1
    return ranks


def _spearman(a: list[float], b: list[float]) -> float:
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((y - mb) ** 2 for y in rb)
    return cov / (va * vb) ** 0.5


def main() -> None:
    rows = []
    declared_all, measured_all, declared_low, medians = [], [], [], []
    for name in sorted(available_apps()):
        app = get_app(name)
        events = run_once(name, seed=0)
        requests = [e for e in events if isinstance(e, EntanglementRequested)]
        sent = sum(isinstance(e, QubitSent) for e in events)
        params = inspect.signature(type(app).__init__).parameters
        in_signature = "min_fidelity" in params
        path = DATA / f"{name}.json"
        threshold = None
        if path.exists():
            threshold = json.loads(path.read_text())["signature"].get("fidelity_threshold")
        if requests:
            fidelities = sorted({r.demand.min_fidelity for r in requests})
            budgets = sorted(
                {
                    r.demand.latency_budget
                    if r.demand.latency_budget is not None
                    else round(r.demand.deadline - r.t, 6)
                    for r in requests
                    if r.demand.latency_budget is not None or r.demand.deadline is not None
                }
            )
            staleness = sorted(
                {r.demand.staleness_tolerance for r in requests if r.demand.staleness_tolerance}
            )
            declared = max(fidelities)
            if threshold is not None:
                signature = json.loads(path.read_text())["signature"]
                declared_all.append(declared)
                measured_all.append(threshold)
                declared_low.append(min(fidelities))
                medians.append(signature.get("fidelity_threshold_seed_median", threshold))
            margin = f"{declared - threshold:+.3f}" if threshold is not None else "n/a"
            where = "constructor default" if in_signature else "hard-coded in the application"
            budget_text = "none"
            if budgets:
                low, high = budgets[0], budgets[-1]
                budget_text = f"{low:g}" if low == high else f"{low:g} to {high:g}"
            rows.append(
                f"| `{name}` | {len(requests)} | {', '.join(f'{f:g}' for f in fidelities)} | "
                f"{budget_text} | {', '.join(f'{s:g}' for s in staleness) or 'none'} | "
                f"{threshold:.3f} | {margin} | {where} |"
                if threshold is not None
                else f"| `{name}` | {len(requests)} | {', '.join(f'{f:g}' for f in fidelities)} | "
                f"{budget_text} | {', '.join(f'{s:g}' for s in staleness) or 'none'} | not reached | "
                f"n/a | {where} |"
            )
        else:
            rows.append(
                f"| `{name}` | 0 | none: {sent} qubits sent directly | none | none | "
                f"{f'{threshold:.3f}' if threshold is not None else 'not reached'} | n/a | no contract |"
            )
    distinct = sorted(set(declared_all) | set(declared_low))
    # Applications with several contracts can be read by their strictest or laxest value, and F½
    # by its mean or its seed median. No choice should be able to change the conclusion.
    variants = [
        (declared, measured)
        for declared in (declared_all, declared_low)
        for measured in (measured_all, medians)
    ]
    correlations = [_spearman(d, m) for d, m in variants]
    belows = [sum(x < y for x, y in zip(d, m, strict=True)) for d, m in variants]
    text = "\n".join(
        [
            "# Contract provenance",
            "",
            "Generated by `scripts/paper/contract_provenance.py`.",
            "",
            "Every contract value is set by hand in the application's code. None is derived from a "
            "measurement, a hardware figure or a citation in that code.",
            "",
            f"- **Tracking:** across {len(declared_all)} applications with both a declared and a "
            "measured value, Spearman between declared `min_fidelity` and measured F½ is between "
            f"{min(correlations):.2f} and {max(correlations):.2f}, depending on whether a multi-"
            "contract application is read by its strictest or laxest value and F½ by its mean or "
            "seed median. An earlier pilot reading F½ from the rendered table got 0.16. Quote it "
            f"as no meaningful correlation. Declared values take only {len(distinct)} distinct "
            f"values ({', '.join(f'{d:g}' for d in distinct)}).",
            f"- **Direction:** {min(belows)} to {max(belows)} of {len(declared_all)} declare less "
            "than the fidelity at which they lose half their utility, so a met contract doesn't "
            "promise a working application.",
            "- **No contract:** applications that use `qsend` make no entanglement request, so they "
            "carry no demand. Treat them as outside any contract-based comparison, and say so.",
            "",
            "| Application | Requests | Declared `min_fidelity` | Budget (s) | Staleness (s) | "
            "Measured F½ | Declared − F½ | Where it's set |",
            "|---|---|---|---|---|---|---|---|",
            *rows,
            "",
        ]
    )
    write_atomic(OUT, text)
    print(text[:1500])


if __name__ == "__main__":
    main()
