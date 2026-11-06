"""What "a run reproduces" means, and that the published corpus actually does.

These regenerate the corpus rather than only checksumming the committed files, which
would pass whether or not the code could still produce them. CI runs the same check
on Linux, macOS and Windows through `qnetbench corpus --check`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from qnetbench.harness.cli import main
from qnetbench.harness.runner import run_once
from qnetbench.spec import check_reference_corpus, generate_reference_corpus
from qnetbench.trace.compare import compare_traces
from qnetbench.trace.events import AppOutcomeEvent, EntanglementDelivered
from qnetbench.trace.io import write_trace

_TRACES = Path(__file__).resolve().parent.parent / "traces"


def _with_one_nudged_fidelity(events: list, factor: float) -> list:
    out = list(events)
    i = next(i for i, e in enumerate(out) if isinstance(e, EntanglementDelivered))
    out[i] = out[i].model_copy(update={"actual_fidelity": out[i].actual_fidelity * factor})
    return out


def test_a_trace_is_equivalent_to_itself() -> None:
    events = run_once("qkd", seed=1)
    result = compare_traces(events, run_once("qkd", seed=1))
    assert result.equivalent
    assert result.max_relative_difference == 0.0


def test_rounding_level_float_differences_are_equivalent() -> None:
    events = run_once("qkd", seed=1)
    result = compare_traces(events, _with_one_nudged_fidelity(events, 1 + 2e-16))
    assert result.equivalent
    assert 0.0 < result.max_relative_difference < 1e-12


def test_a_larger_float_difference_is_not_equivalent() -> None:
    events = run_once("qkd", seed=1)
    result = compare_traces(events, _with_one_nudged_fidelity(events, 1 + 1e-6))
    assert not result.equivalent
    assert "actual_fidelity" in (result.first_difference or "")


def test_different_seeds_are_not_equivalent() -> None:
    assert not compare_traces(run_once("qkd", seed=1), run_once("qkd", seed=2)).equivalent


def test_a_missing_event_is_not_equivalent() -> None:
    events = run_once("qkd", seed=1)
    result = compare_traces(events, events[:-1])
    assert not result.equivalent
    assert "event count" in (result.first_difference or "")


def test_traces_use_lf_line_endings_on_every_platform(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    write_trace(path, run_once("qkd", seed=1))
    assert b"\r" not in path.read_bytes()


def test_published_corpus_regenerates() -> None:
    check = check_reference_corpus(_TRACES)
    assert check.ok, check.different
    assert len(check.byte_identical) + len(check.rounding_only) >= 27


def test_corpus_check_catches_a_changed_outcome(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    generate_reference_corpus(corpus)
    path = corpus / "qkd.jsonl"
    lines = path.read_text().splitlines()
    changed = []
    for line in lines:
        event = json.loads(line)
        if event["kind"] == AppOutcomeEvent.model_fields["kind"].default:
            event["utility"] = 0.0 if event["utility"] > 0.0 else 1.0
        changed.append(json.dumps(event))
    path.write_text("\n".join(changed) + "\n")

    check = check_reference_corpus(corpus)
    assert not check.ok
    assert [app for app, _ in check.different] == ["qkd"]
    assert "utility" in check.different[0][1]


def test_corpus_check_reports_a_missing_trace(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    generate_reference_corpus(corpus)
    (corpus / "bb84.jsonl").unlink()
    assert [app for app, _ in check_reference_corpus(corpus).different] == ["bb84"]


def test_cli_check_writes_nothing_and_signals_through_its_exit_code(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    shutil.copytree(_TRACES, corpus)
    before = {p.name: p.read_bytes() for p in corpus.iterdir()}
    assert main(["corpus", "--check", "--out", str(corpus)]) == 0
    assert {p.name: p.read_bytes() for p in corpus.iterdir()} == before

    (corpus / "bb84.jsonl").unlink()
    assert main(["corpus", "--check", "--out", str(corpus)]) == 1


def test_corpus_manifest_records_its_environment() -> None:
    environment = json.loads((_TRACES / "manifest.json").read_text())["environment"]
    assert set(environment) == {"python", "numpy", "platform", "machine"}
