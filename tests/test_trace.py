"""Trace schema: round-trip fidelity, versioning, and discriminated-union parsing."""

from __future__ import annotations

from pathlib import Path

from qnetbench.api.types import Demand
from qnetbench.harness.runner import run_once
from qnetbench.trace.events import (
    SCHEMA_VERSION,
    EntanglementRequested,
    RunHeader,
)
from qnetbench.trace.io import parse_event, read_trace, write_trace


def test_every_event_type_round_trips() -> None:
    events = run_once("distributed_gate", seed=0)
    for ev in events:
        assert parse_event(parse_event(ev.model_dump_json()).model_dump_json()) == ev


def test_header_carries_schema_and_provenance() -> None:
    events = run_once("qkd", seed=0)
    header = events[0]
    assert isinstance(header, RunHeader)
    assert header.schema_version == SCHEMA_VERSION
    assert header.app == "qkd"
    assert header.backend == "reference"
    assert header.arbitration == "native"


def test_discriminator_selects_the_right_model() -> None:
    demand = Demand(min_fidelity=0.9)
    line = EntanglementRequested(
        t=1.0, req_id=7, src="alice", dst="bob", n=2, demand=demand
    ).model_dump_json()
    parsed = parse_event(line)
    assert isinstance(parsed, EntanglementRequested)
    assert parsed.req_id == 7
    assert parsed.demand.min_fidelity == 0.9


def test_write_then_read_file(tmp_path: Path) -> None:
    events = run_once("bqc", seed=1)
    path = tmp_path / "run.jsonl"
    write_trace(path, events)
    restored = list(read_trace(path))
    assert [e.model_dump() for e in restored] == [e.model_dump() for e in events]
