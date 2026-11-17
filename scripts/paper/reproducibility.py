"""How far does a run reproduce across environments?

A run is easily described as reproducing "byte for byte". This measures
what actually holds, by running every core application over several seeds in each
environment and comparing the traces afterwards.

    python reproducibility.py generate DIR [--seeds 16]
    python reproducibility.py compare BASELINE_DIR OTHER_DIR [OTHER_DIR ...]

`generate` writes one trace per application and seed, plus the environment it ran in.
`compare` reports, for each other environment against the baseline: traces identical
byte for byte, traces with the same events and floats within a relative 1e-12, traces
with identical application outcomes, and the largest float difference seen. Reference
backend only: the simulator backends replay through the same engine.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qnetbench.apps import available_apps
from qnetbench.characterize.provenance import runtime_environment
from qnetbench.harness.runner import run_once
from qnetbench.trace.compare import compare_traces
from qnetbench.trace.events import AppOutcomeEvent, Event
from qnetbench.trace.io import read_trace, write_trace

ENV_FILE = "environment.json"


def generate(out: Path, seeds: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    apps = available_apps()
    for app in apps:
        for seed in range(seeds):
            write_trace(out / f"{app}.{seed}.jsonl", run_once(app, seed=seed))
    env = {**runtime_environment(), "apps": len(apps), "seeds": seeds}
    (out / ENV_FILE).write_text(json.dumps(env, indent=2) + "\n", newline="\n")
    print(f"{len(apps) * seeds} traces written to {out}/")


def _outcomes(events: list[Event]) -> list[tuple[str, bool, float]]:
    return [(e.role, e.success, e.utility) for e in events if isinstance(e, AppOutcomeEvent)]


def compare(baseline: Path, others: list[Path]) -> None:
    files = sorted(baseline.glob("*.jsonl"))
    base_env = json.loads((baseline / ENV_FILE).read_text())
    print(f"baseline {baseline.name}: {_describe(base_env)}")
    print(f"{len(files)} traces ({base_env['apps']} applications x {base_env['seeds']} seeds)\n")
    print(f"{'environment':<34} {'bytes':>7} {'events':>7} {'outcomes':>9} {'max rel diff':>13}")
    print("-" * 74)
    notes: list[str] = []
    outcome_notes: list[str] = []
    for other in others:
        env = json.loads((other / ENV_FILE).read_text())
        identical = equivalent = same_outcome = 0
        max_rel = 0.0
        for path in files:
            twin = other / path.name
            if path.read_bytes() == twin.read_bytes():
                identical += 1
                equivalent += 1
                same_outcome += 1
                continue
            a, b = list(read_trace(path)), list(read_trace(twin))
            result = compare_traces(a, b)
            max_rel = max(max_rel, result.max_relative_difference)
            equivalent += result.equivalent
            if _outcomes(a) == _outcomes(b):
                same_outcome += 1
            else:
                largest = max(
                    abs(x[2] - y[2]) for x, y in zip(_outcomes(a), _outcomes(b), strict=True)
                )
                outcome_notes.append(f"{other.name}: {path.name}: utility differs by {largest:.1e}")
            if not result.equivalent:
                notes.append(f"{other.name}: {path.name}: {result.first_difference}")
        print(
            f"{_describe(env):<34} {identical:>7} {equivalent:>7} {same_outcome:>9} "
            f"{max_rel:>13.2e}"
        )
    print(
        f"\nOut of {len(files)}. 'bytes' is an identical file. 'events' is the same events "
        "in order,\nwith floats within a relative 1e-12. 'outcomes' is an exactly equal "
        "role, success and utility."
    )
    if outcome_notes:
        print("\nOutcomes not exactly equal:")
        for note in outcome_notes:
            print(f"  {note}")
    if notes:
        print("\nNot equivalent:")
        for note in notes:
            print(f"  {note}")


def _describe(env: dict[str, object]) -> str:
    system = str(env["platform"]).split("-")[0]
    return f"{system} {env['machine']} py{env['python']} np{env['numpy']}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("out", type=Path)
    gen.add_argument("--seeds", type=int, default=16)
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("baseline", type=Path)
    cmp_.add_argument("others", type=Path, nargs="+")
    args = parser.parse_args()
    if args.command == "generate":
        generate(args.out, args.seeds)
    else:
        compare(args.baseline, args.others)


if __name__ == "__main__":
    main()
