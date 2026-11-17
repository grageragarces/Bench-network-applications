"""The versioned, machine-readable trace and metric specification (Deliverable 3).

`trace_json_schema()` / `metric_json_schema()` emit JSON Schemas generated from the
pydantic models, so the committed spec can never drift from the code (a test
regenerates and diffs them). `generate_reference_corpus()` produces the published
reference traces a third-party scheduler can consume without importing qnetbench.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from qnetbench.apps import available_apps
from qnetbench.characterize.provenance import runtime_environment
from qnetbench.harness.runner import run_once
from qnetbench.metrics.report import Report
from qnetbench.trace.compare import compare_traces
from qnetbench.trace.events import SCHEMA_VERSION, Event
from qnetbench.trace.io import read_trace, write_trace

# Trace and metric specs are versioned together, tracking the trace schema version.
SPEC_VERSION = SCHEMA_VERSION


@dataclass(frozen=True)
class CorpusCheck:
    """How far a regenerated corpus matches the published one in this environment."""

    byte_identical: tuple[str, ...]
    rounding_only: tuple[str, ...]  # same events; floats differ within tolerance
    different: tuple[tuple[str, str], ...]  # (application, first difference)
    max_relative_difference: float
    environment: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.different


def trace_json_schema() -> dict[str, Any]:
    """JSON Schema for a single trace event (the tagged union of event types)."""
    return TypeAdapter(Event).json_schema()


def metric_json_schema() -> dict[str, Any]:
    """JSON Schema for the standard metric report."""
    return Report.model_json_schema()


def _dump(schema: dict[str, Any]) -> str:
    # Stable, sorted output so the committed file and the drift test agree.
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def write_specs(out_dir: str | Path) -> list[Path]:
    """Write the trace and metric JSON Schemas to `out_dir`."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    schemas = {
        "trace-schema.json": trace_json_schema(),
        "metric-schema.json": metric_json_schema(),
    }
    paths = []
    for name, schema in schemas.items():
        path = out / name
        path.write_text(_dump(schema), encoding="utf-8", newline="\n")
        paths.append(path)
    return paths


def generate_reference_corpus(out_dir: str | Path, seed: int = 0) -> dict[str, Any]:
    """Run every application once on the reference backend and write the JSONL
    traces plus a manifest (spec version, seed, per-trace sha256 + event count)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    entries = []
    for app in available_apps():
        events = run_once(app, seed=seed, backend="reference")
        path = out / f"{app}.jsonl"
        write_trace(path, events)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append({"app": app, "file": path.name, "n_events": len(events), "sha256": digest})
    manifest = {
        "spec_version": SPEC_VERSION,
        "backend": "reference",
        "seed": seed,
        # Checksums hold byte for byte in this environment. Across others, expect
        # rounding-level differences in floats: see `check_reference_corpus`.
        "environment": runtime_environment(),
        "traces": entries,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest


def check_reference_corpus(corpus_dir: str | Path, *, rel_tol: float = 1e-12) -> CorpusCheck:
    """Regenerate a published corpus here and compare it with the published files.

    Reports byte-identical traces separately from traces that hold the same events
    with floats differing by no more than `rel_tol`, which is what a different numpy
    or platform can produce. Anything else is a real difference.
    """
    corpus = Path(corpus_dir)
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    identical: list[str] = []
    rounding: list[str] = []
    different: list[tuple[str, str]] = []
    max_rel = 0.0
    with tempfile.TemporaryDirectory() as tmp:
        for entry in manifest["traces"]:
            app, published = entry["app"], corpus / entry["file"]
            events = run_once(app, seed=manifest["seed"], backend=manifest["backend"])
            fresh = Path(tmp) / entry["file"]
            write_trace(fresh, events)
            if not published.exists():
                different.append((app, "published trace is missing"))
            elif fresh.read_bytes() == published.read_bytes():
                identical.append(app)
            else:
                result = compare_traces(list(read_trace(published)), events, rel_tol=rel_tol)
                max_rel = max(max_rel, result.max_relative_difference)
                if result.equivalent:
                    rounding.append(app)
                else:
                    different.append((app, result.first_difference or "unknown difference"))
    return CorpusCheck(
        tuple(identical), tuple(rounding), tuple(different), max_rel, runtime_environment()
    )
