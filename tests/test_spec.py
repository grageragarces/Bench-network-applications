"""The versioned spec (Deliverable 3): schema drift guards + reference-corpus
integrity."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from qnetbench.spec import (
    SPEC_VERSION,
    metric_json_schema,
    trace_json_schema,
)
from qnetbench.trace.events import RunHeader
from qnetbench.trace.io import read_trace

_ROOT = Path(__file__).resolve().parent.parent
_SPECS = _ROOT / "docs" / "specs"
_TRACES = _ROOT / "traces"


def test_trace_schema_matches_committed() -> None:
    committed = json.loads((_SPECS / "trace-schema.json").read_text())
    assert committed == trace_json_schema(), "trace schema drifted; run `qnetbench spec`"


def test_metric_schema_matches_committed() -> None:
    committed = json.loads((_SPECS / "metric-schema.json").read_text())
    assert committed == metric_json_schema(), "metric schema drifted; run `qnetbench spec`"


def test_reference_corpus_manifest_is_consistent() -> None:
    manifest = json.loads((_TRACES / "manifest.json").read_text())
    assert manifest["spec_version"] == SPEC_VERSION
    assert manifest["traces"], "no reference traces published"
    for entry in manifest["traces"]:
        path = _TRACES / entry["file"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == entry["sha256"], f"{entry['file']} changed; run `qnetbench corpus`"


@pytest.mark.parametrize(
    "name",
    ["qkd", "bqc", "distributed_gate", "chsh", "clock_sync", "anonymous_transmission"],
)
def test_published_traces_round_trip(name: str) -> None:
    events = list(read_trace(_TRACES / f"{name}.jsonl"))
    assert events, f"{name} trace is empty"
    header = events[0]
    assert isinstance(header, RunHeader)
    assert header.schema_version == SPEC_VERSION
    assert header.app == name
