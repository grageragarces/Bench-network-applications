"""`qnetbench` command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from qnetbench.apps import available_apps, catalog_apps
from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report, render
from qnetbench.policies import available_policies
from qnetbench.trace.io import write_trace


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qnetbench", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one application and print its report")
    run.add_argument("app", metavar="APP", help="benchmark name (any from `list --all`)")
    run.add_argument("--backend", default="reference")
    run.add_argument(
        "--arbitration",
        default="native",
        help="'native' or 'policy:<name>'; policies: " + ", ".join(available_policies()),
    )
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--out", help="write the JSONL trace to this path")
    run.add_argument("--json", action="store_true", help="print the report as JSON")

    ls = sub.add_parser("list", help="list available apps and policies")
    ls.add_argument("--all", action="store_true", help="list the full catalog (50+), not just core")

    ch = sub.add_parser(
        "characterize", help="measure demand signatures (one app, or all core apps)"
    )
    ch.add_argument("app", nargs="?", metavar="APP", help="omit to characterize all core apps")
    ch.add_argument("--seeds", type=int, default=8, help="seeds averaged per sweep point")
    ch.add_argument("--out", help="directory to write per-app signature+curve JSON")

    sp = sub.add_parser("spec", help="write the versioned trace + metric JSON Schemas")
    sp.add_argument("--out", default="docs/specs", help="output directory (default: docs/specs)")

    co = sub.add_parser("corpus", help="write the published reference traces + manifest")
    co.add_argument("--out", default="traces", help="output directory (default: traces)")
    co.add_argument("--seed", type=int, default=0)

    sub.add_parser(
        "contention",
        help="run the multi-tenant cross-policy evaluation (the ranking-inversion result)",
    )
    return parser


def _characterize(app: str | None, seeds: int, out: str | None) -> int:
    from qnetbench.characterize import characterize_app, render_table

    apps = [app] if app else available_apps()
    signatures = []
    for name in apps:
        signature, curves = characterize_app(name, seeds=range(seeds))
        signatures.append(signature)
        if out:
            out_dir = Path(out)
            out_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "signature": signature.model_dump(),
                "fidelity_curve": curves.fidelity.as_rows(),
                "staleness_curve": curves.staleness.as_rows(),
            }
            (out_dir / f"{name}.json").write_text(json.dumps(payload, indent=2))
    print(render_table(signatures))
    if out:
        print(f"\nper-app signature + curve data written to {out}/")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "list":
        apps = catalog_apps() if args.all else available_apps()
        label = f"catalog ({len(apps)})" if args.all else "core"
        print(f"apps [{label}]: " + ", ".join(apps))
        print("policies:     " + ", ".join(available_policies()))
        return 0

    if args.command == "characterize":
        return _characterize(args.app, args.seeds, args.out)

    if args.command == "spec":
        from qnetbench.spec import SPEC_VERSION, write_specs

        paths = write_specs(args.out)
        print(f"spec v{SPEC_VERSION} written:")
        for path in paths:
            print(f"  {path}")
        return 0

    if args.command == "corpus":
        from qnetbench.spec import generate_reference_corpus

        manifest = generate_reference_corpus(args.out, seed=args.seed)
        print(f"reference corpus v{manifest['spec_version']} written to {args.out}/ "
              f"({len(manifest['traces'])} traces)")
        return 0

    if args.command == "contention":
        from qnetbench.contention import default_experiment, render_experiment

        print(render_experiment(default_experiment()))
        return 0

    try:
        events = run_once(
            args.app, seed=args.seed, backend=args.backend, arbitration=args.arbitration
        )
    except KeyError as exc:
        print(str(exc).strip('"'), file=sys.stderr)
        return 2
    if args.out:
        write_trace(args.out, events)
    report = compute_report(events)
    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(render(report))
        if args.out:
            print(f"\ntrace written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
