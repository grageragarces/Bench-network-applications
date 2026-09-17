"""`qnetbench` command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from qnetbench.apps import available_apps, catalog_apps
from qnetbench.characterize.curves import SEEDS
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
    ch.add_argument(
        "--seeds", type=int, default=SEEDS, help="seeds averaged per sweep point"
    )
    ch.add_argument("--out", help="directory to write per-app signature+curve JSON")
    ch.add_argument(
        "--latex",
        action="store_true",
        help="print the table as a booktabs tabular (also always written to --out/table.tex)",
    )

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


def _characterize(app: str | None, seeds: int, out: str | None, latex: bool = False) -> int:
    from qnetbench.characterize import characterize_app, render_latex, render_table
    from qnetbench.characterize.provenance import finish_run, start_run, write_atomic

    apps = [app] if app else available_apps()
    out_dir = Path(out) if out else None
    # Stamp the directory before writing anything, so a run that dies part way
    # leaves a manifest saying so rather than a directory that looks finished.
    manifest = start_run(out_dir, apps, seeds) if out_dir is not None else None
    signatures = []
    for name in apps:
        signature, curves = characterize_app(name, seeds=range(seeds))
        signatures.append(signature)
        if out_dir is not None and manifest is not None:
            payload = {
                "run_id": manifest.run_id,
                "signature": signature.model_dump(),
                "fidelity_curve": curves.fidelity.as_rows(),
                "staleness_curve": curves.staleness.as_rows(),
            }
            write_atomic(out_dir / f"{name}.json", json.dumps(payload, indent=2) + "\n")
    print(render_latex(signatures) if latex else render_table(signatures))
    if out_dir is not None and manifest is not None:
        # Written by the tool, not by a shell redirect: `> table.txt` truncates at
        # launch, so an interrupted run used to leave an empty file where a reader
        # expected a table. table.tex is what the manuscript \input{}s, so the
        # paper's table cannot be transcribed by hand and drift.
        write_atomic(out_dir / "table.txt", render_table(signatures) + "\n")
        write_atomic(out_dir / "table.tex", render_latex(signatures))
        finish_run(out_dir, manifest)
        print(f"\nper-app signature + curve data written to {out_dir}/")
        print(f"tables written to {out_dir}/table.txt and {out_dir}/table.tex")
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
        return _characterize(args.app, args.seeds, args.out, args.latex)

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
