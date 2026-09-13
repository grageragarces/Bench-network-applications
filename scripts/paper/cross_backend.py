#!/usr/bin/env python3
"""Cross-backend equivalence across the whole core suite (Sec. VII, Table IV).

Goal G4 says an application written once must behave equivalently on every
backend. The paper previously evidenced that with a single application on a
single seed, which shows the *shape* of the claim but not its coverage. This
script runs every core application on every available backend and reports, per
application, whether the application-level outcome agrees.

The two simulators pin mutually exclusive NumPy versions and cannot share an
environment, so this runs in two passes and merges:

    .venv/bin/python    scripts/paper/cross_backend.py --backends reference,sequence \
        --out scripts/paper/data/cross_backend_ref_seq.json
    .venv-ns/bin/python scripts/paper/cross_backend.py --backends netsquid \
        --out scripts/paper/data/cross_backend_ns.json
    python scripts/paper/cross_backend.py --merge scripts/paper/data/cross_backend_*.json \
        > scripts/paper/data/cross_backend.txt

Supply-side metrics (rate, latency) are *expected* to differ between backends —
that is the point of the replay model. Only the application-level outcome
(success, and utility to a tolerance) is asserted to agree.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

UTILITY_TOL = 1e-6  # exact agreement expected; a tolerance guards float formatting


def _topology_for(app: str, fidelity_std: float) -> Any:
    """The app's default topology, but with the link's fidelity spread overridden.

    The reference backend samples each pair's delivered fidelity from
    N(link_fidelity, fidelity_std), while the replay backends inherit a constant
    delivered fidelity from the simulator's supply stream. With the default
    fidelity_std=0.01 the three backends are therefore *not* being given the same
    entanglement, so comparing application outcomes across them measures the link
    model rather than the application. Setting the spread to zero equalises supply
    and isolates the property G4 actually claims.
    """
    from qnetbench.apps import get_app
    from qnetbench.topology import LinkModel, line2, star

    roles = get_app(app).roles()
    link = LinkModel(fidelity_std=fidelity_std)
    if len(roles) == 2:
        return line2(roles[0], roles[1], link=link)
    return star(roles[0], list(roles[1:]), link=link)


def run_all(backends: list[str], seed: int, fidelity_std: float | None) -> dict[str, dict[str, Any]]:
    from qnetbench.apps import available_apps
    from qnetbench.harness.runner import run_once
    from qnetbench.metrics import compute_report

    out: dict[str, dict[str, Any]] = {}
    for app in sorted(available_apps()):
        out[app] = {}
        for backend in backends:
            try:
                kwargs: dict[str, Any] = {}
                if fidelity_std is not None:
                    kwargs["topology"] = _topology_for(app, fidelity_std)
                rep = compute_report(run_once(app, seed=seed, backend=backend, **kwargs))
                out[app][backend] = {
                    "success": rep.app_success,
                    "utility": rep.app_utility,
                    "delivered": rep.n_delivered,
                    "rate": rep.delivered_rate,
                }
            except Exception as exc:  # a backend that cannot run an app is a result
                out[app][backend] = {"error": f"{type(exc).__name__}: {exc}"}
        print(f"  {app}: {list(out[app])}", flush=True)
    return out


def render(merged: dict[str, dict[str, Any]]) -> str:
    """Report the spread, not just a pass/fail flag.

    Exact equality is the wrong headline on its own: the backends deliver
    *different* entanglement, so a small spread in a continuous outcome metric is
    the model working as intended, while a large one means the application is
    genuinely supply-sensitive. Reporting max|du| lets the reader tell them apart.
    """
    backends = ["reference", "sequence", "netsquid"]
    hdr = f"{'app':26}" + "".join(f"{b:>14}" for b in backends) + f"{'max|du|':>10}"
    lines = [hdr, "-" * len(hdr)]
    n_exact = n_close = n_total = 0
    for app in sorted(merged):
        row = merged[app]
        cells: list[str] = []
        utils: list[float] = []
        for b in backends:
            r = row.get(b)
            if r is None:
                cell = "-"
            elif "error" in r:
                cell = "ERROR"
            else:
                cell = f"{r['utility']:.4f}"
                utils.append(r["utility"])
            cells.append(f"{cell:>14}")
        if len(utils) > 1:
            spread = max(utils) - min(utils)
            n_total += 1
            n_exact += spread <= UTILITY_TOL
            n_close += spread <= 0.02
            cells.append(f"{spread:>10.4f}")
        else:
            cells.append(f"{'-':>10}")
        lines.append(f"{app:26}" + "".join(cells))
    lines += [
        "",
        f"{n_exact}/{n_total} identical (tolerance {UTILITY_TOL}); "
        f"{n_close}/{n_total} agree within 0.02 utility.",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backends", help="comma-separated backends to run")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fidelity-std", type=float, default=None,
                    help="override the link fidelity spread; 0 equalises supply across backends")
    ap.add_argument("--out", help="write raw results JSON here")
    ap.add_argument("--merge", nargs="*", help="merge these result JSONs and render")
    args = ap.parse_args()

    if args.merge:
        merged: dict[str, dict[str, Any]] = {}
        for f in args.merge:
            for app, row in json.loads(Path(f).read_text()).items():
                merged.setdefault(app, {}).update(row)
        print(render(merged))
        return

    results = run_all(args.backends.split(","), args.seed, args.fidelity_std)
    Path(args.out).write_text(json.dumps(results, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
