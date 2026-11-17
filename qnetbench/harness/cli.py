"""`qnetbench` command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from qnetbench.apps import available_apps, catalog_apps, get_app
from qnetbench.backends.reference.engine import ApplicationFailure
from qnetbench.characterize.curves import SEEDS
from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report, render
from qnetbench.policies import available_policies
from qnetbench.topology import LinkModel, Topology, default_topology
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
    link = run.add_argument_group("link parameters (every link of the default topology)")
    link.add_argument("--link-fidelity", type=float, help="mean delivered fidelity")
    link.add_argument("--fidelity-std", type=float, help="spread of the delivered fidelity")
    link.add_argument(
        "--attempt-latency",
        type=float,
        help="seconds per delivered pair on the reference backend; "
        "the simulator backends currently use it as the classical delay",
    )
    contract = run.add_argument_group("contract overrides (every entanglement request)")
    contract.add_argument("--min-fidelity", type=float)
    contract.add_argument(
        "--latency-budget",
        type=float,
        help="seconds from request; replaces the application's own deadline",
    )
    contract.add_argument("--staleness-tolerance", type=float, help="maximum pair age, seconds")
    contract.add_argument("--priority", type=float)

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
    co.add_argument(
        "--check",
        action="store_true",
        help="regenerate the corpus in --out here and compare; writes nothing",
    )

    cont = sub.add_parser(
        "contention",
        help="compare scheduling policies on contended workload mixes",
    )
    cont.add_argument("--capacity", type=float, help="link capacity, pairs/s (default: 160)")
    cont.add_argument("--coherence-time", type=float, help="seconds (default: 0.25)")
    cont.add_argument("--link-fidelity", type=float, help="default: 0.99")
    cont.add_argument("--draws", type=int, help="independent arrival draws (default: 32)")
    cont.add_argument("--requests", type=int, help="requests per tenant (default: 100)")
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


def _check_corpus(corpus_dir: str) -> int:
    from qnetbench.spec import check_reference_corpus

    check = check_reference_corpus(corpus_dir)
    env = check.environment
    total = len(check.byte_identical) + len(check.rounding_only) + len(check.different)
    print(f"environment: python {env['python']}, numpy {env['numpy']}, {env['platform']}")
    print(f"{total} traces regenerated from {corpus_dir}/:")
    print(f"  {len(check.byte_identical)} byte-identical")
    print(f"  {len(check.rounding_only)} same events, floats differ only by rounding", end="")
    print(f" (largest relative difference {check.max_relative_difference:.2e})")
    print(f"  {len(check.different)} different")
    for app in check.rounding_only:
        print(f"    rounding only: {app}")
    for app, reason in check.different:
        print(f"    DIFFERENT: {app}: {reason}")
    return 0 if check.ok else 1


def _run_topology(args: argparse.Namespace) -> Topology | None:
    fields = {
        name: getattr(args, name)
        for name in ("link_fidelity", "fidelity_std", "attempt_latency")
        if getattr(args, name) is not None
    }
    if not fields:
        return None
    return default_topology(get_app(args.app).roles(), replace(LinkModel(), **fields))


def _run_contract(args: argparse.Namespace) -> dict[str, object]:
    return {
        name: getattr(args, name)
        for name in ("min_fidelity", "latency_budget", "staleness_tolerance", "priority")
        if getattr(args, name) is not None
    }


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

        if args.check:
            return _check_corpus(args.out)

        manifest = generate_reference_corpus(args.out, seed=args.seed)
        print(f"reference corpus v{manifest['spec_version']} written to {args.out}/ "
              f"({len(manifest['traces'])} traces)")
        return 0

    if args.command == "contention":
        from qnetbench.contention import render_replicated, replicated_experiment

        options = {
            "capacity": args.capacity,
            "coherence_time": args.coherence_time,
            "link_fidelity": args.link_fidelity,
            "draws": args.draws,
            "n_requests": args.requests,
        }
        chosen = {name: value for name, value in options.items() if value is not None}
        print(render_replicated(replicated_experiment(**chosen)))
        return 0

    try:
        events = run_once(
            args.app,
            seed=args.seed,
            backend=args.backend,
            arbitration=args.arbitration,
            topology=_run_topology(args),
            demand_override=_run_contract(args),
        )
    except KeyError as exc:
        print(str(exc).strip('"'), file=sys.stderr)
        return 2
    except ValueError as exc:  # includes an out-of-range contract override
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ApplicationFailure as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
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
