"""Run provenance for generated characterization data.

These cover the failure that actually happened: a directory holding two
characterization runs at once, with nothing in it saying so.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qnetbench.characterize import RunConsistencyError, verify_run
from qnetbench.characterize.provenance import MANIFEST_NAME, finish_run, start_run, write_atomic
from qnetbench.harness.cli import main


def _write_app(out: Path, name: str, run_id: str) -> None:
    payload = {"run_id": run_id, "signature": {"app": name}, "fidelity_curve": []}
    write_atomic(out / f"{name}.json", json.dumps(payload))


def test_complete_run_verifies(tmp_path: Path) -> None:
    manifest = start_run(tmp_path, ["alpha", "beta"], seeds=4)
    _write_app(tmp_path, "alpha", manifest.run_id)
    _write_app(tmp_path, "beta", manifest.run_id)
    finish_run(tmp_path, manifest)
    assert verify_run(tmp_path).run_id == manifest.run_id


def test_interrupted_run_is_rejected(tmp_path: Path) -> None:
    manifest = start_run(tmp_path, ["alpha", "beta"], seeds=4)
    _write_app(tmp_path, "alpha", manifest.run_id)  # died before beta
    with pytest.raises(RunConsistencyError, match="unfinished run"):
        verify_run(tmp_path)


def test_mixed_runs_are_rejected(tmp_path: Path) -> None:
    """The Table III failure: a second run overwrites only part of a directory."""
    first = start_run(tmp_path, ["alpha", "beta"], seeds=4)
    _write_app(tmp_path, "alpha", first.run_id)
    _write_app(tmp_path, "beta", first.run_id)
    finish_run(tmp_path, first)

    second = start_run(tmp_path, ["alpha", "beta"], seeds=4)
    _write_app(tmp_path, "alpha", second.run_id)  # interrupted before beta
    finish_run(tmp_path, second)  # even a "complete" manifest must not hide it

    with pytest.raises(RunConsistencyError, match="does not hold a single characterization run"):
        verify_run(tmp_path)


def test_directory_without_a_manifest_is_rejected(tmp_path: Path) -> None:
    _write_app(tmp_path, "alpha", "whatever")
    with pytest.raises(RunConsistencyError, match="not found"):
        verify_run(tmp_path)


def test_characterize_writes_manifest_and_tables(tmp_path: Path) -> None:
    assert main(["characterize", "qkd", "--seeds", "2", "--out", str(tmp_path)]) == 0
    manifest = verify_run(tmp_path)
    assert manifest.apps == ["qkd"] and manifest.complete and manifest.seeds == 2
    assert (tmp_path / MANIFEST_NAME).exists()
    assert "qkd" in (tmp_path / "table.txt").read_text()
    tex = (tmp_path / "table.tex").read_text()
    assert r"\begin{tabular}" in tex and r"\code{qkd}" in tex
    # every per-app file is stamped with the run that wrote it
    payload = json.loads((tmp_path / "qkd.json").read_text())
    assert payload["run_id"] == manifest.run_id
