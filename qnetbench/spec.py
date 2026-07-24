"""The versioned, machine-readable trace and metric specification (Deliverable 3).

`trace_json_schema()` / `metric_json_schema()` emit JSON Schemas generated from the
pydantic models, so the committed spec can never drift from the code (a test
regenerates and diffs them). `generate_reference_corpus()` produces the published
reference traces a third-party scheduler can consume without importing qnetbench.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from qnetbench.apps import available_apps
from qnetbench.harness.runner import run_once
from qnetbench.metrics.report import Report
from qnetbench.trace.events import SCHEMA_VERSION, Event
from qnetbench.trace.io import write_trace

# Trace and metric specs are versioned together, tracking the trace schema version.
SPEC_VERSION = SCHEMA_VERSION


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
        path.write_text(_dump(schema))
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
        "traces": entries,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
