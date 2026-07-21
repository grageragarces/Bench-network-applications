"""`qnetbench` command-line entry point."""

from __future__ import annotations

import argparse
import sys

from qnetbench.apps import available_apps
from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report, render
from qnetbench.policies import available_policies
from qnetbench.trace.io import write_trace


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qnetbench", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one application and print its report")
    run.add_argument("app", choices=available_apps())
    run.add_argument("--backend", default="reference")
    run.add_argument(
        "--arbitration",
        default="native",
        help="'native' or 'policy:<name>'; policies: " + ", ".join(available_policies()),
    )
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--out", help="write the JSONL trace to this path")
    run.add_argument("--json", action="store_true", help="print the report as JSON")

    sub.add_parser("list", help="list available apps and policies")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "list":
        print("apps:     " + ", ".join(available_apps()))
        print("policies: " + ", ".join(available_policies()))
        return 0

    events = run_once(
        args.app, seed=args.seed, backend=args.backend, arbitration=args.arbitration
    )
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
