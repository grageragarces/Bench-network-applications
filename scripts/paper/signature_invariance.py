#!/usr/bin/env python3
"""Is a demand signature a property of the application, or of the link model?

Section VI measures burstiness, classical coupling and multipartiteness from a
single trace on the reference backend, and calls the result a property of the
application. That deserves a check rather than an assumption: inter-request
times are set by when the previous delivery completed, so they are in principle
a joint property of the application's control flow and whatever supplied the
entanglement. The three backends differ in delivered rate by more than a factor
of two, which is exactly the kind of difference that could move them.

This runs the single-trace signature on every available backend and reports, per
axis, how far apart the backends land. Run it once per environment, since the
simulators cannot share one:

    .venv/bin/python scripts/paper/signature_invariance.py \\
        --backends reference,sequence \\
        --out scripts/paper/data/signature_invariance/ref_seq.json
    .venv-ns/bin/python scripts/paper/signature_invariance.py --backends netsquid \\
        --out scripts/paper/data/signature_invariance/ns.json
    python scripts/paper/signature_invariance.py \\
        --merge scripts/paper/data/signature_invariance/*.json \\
        > scripts/paper/data/signature_invariance/summary.txt
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

AXES = ("request_cv", "fano_factor", "msgs_per_pair", "bytes_per_pair", "n_parties")


def run_all(backends: list[str]) -> dict[str, dict[str, Any]]:
    from qnetbench.apps import available_apps
    from qnetbench.characterize import characterize_trace
    from qnetbench.harness.runner import run_once

    out: dict[str, dict[str, Any]] = {}
    for app in available_apps():
        out[app] = {}
        for backend in backends:
            try:
                sig = characterize_trace(run_once(app, seed=0, backend=backend))
            except Exception as exc:  # a backend that cannot run this app
                out[app][backend] = {"error": f"{type(exc).__name__}: {exc}"[:120]}
                continue
            out[app][backend] = {a: getattr(sig, a) for a in AXES}
    return out


def merge(paths: list[str]) -> None:
    merged: dict[str, dict[str, Any]] = {}
    for p in paths:
        for app, per_backend in json.loads(Path(p).read_text()).items():
            merged.setdefault(app, {}).update(per_backend)
    backends = sorted({b for v in merged.values() for b in v})

    print("Demand-signature axes across backends (single trace, seed 0).")
    print(f"backends: {', '.join(backends)}\n")
    header = f"{'application':<26} " + " ".join(f"{a:>14}" for a in AXES)
    print(header)
    print("-" * len(header))
    worst: dict[str, float] = dict.fromkeys(AXES, 0.0)
    identical = 0
    errors: list[str] = []
    for app in sorted(merged):
        per = merged[app]
        usable = {b: v for b, v in per.items() if "error" not in v}
        for b, v in per.items():
            if "error" in v:
                errors.append(f"{app}/{b}: {v['error']}")
        if len(usable) < 2:
            continue
        cells, same = [], True
        for axis in AXES:
            vals = [v[axis] for v in usable.values()]
            spread = max(vals) - min(vals)
            rel = spread / abs(max(vals)) if max(vals) else 0.0
            worst[axis] = max(worst[axis], rel)
            same &= spread == 0
            cells.append(f"{vals[0]:8.3f}{'  =' if spread == 0 else f' {rel:+5.1%}'}")
        identical += same
        print(f"{app:<26} " + " ".join(f"{c:>14}" for c in cells))
    print(f"\n{identical} of {len(merged)} applications: every axis identical on every backend.")
    print("worst relative spread per axis: " + ", ".join(
        f"{a} {worst[a]:.1%}" for a in AXES))
    if errors:
        print("\nbackends that could not run an application:")
        for e in errors:
            print(f"  {e}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backends", default="reference")
    ap.add_argument("--out")
    ap.add_argument("--merge", nargs="*")
    args = ap.parse_args()
    if args.merge:
        merge(args.merge)
        return
    data = run_all(args.backends.split(","))
    if args.out:
        Path(args.out).write_text(json.dumps(data, indent=2))
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
