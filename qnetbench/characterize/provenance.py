"""Run provenance for generated characterization data.

A characterization run writes one JSON file per application, incrementally, over
several minutes. If it dies half way the directory still *looks* finished: the
files present are individually valid, they are simply from two different runs, and
nothing in them says so. A later consumer — a plotting script, a paper table —
then silently mixes them.

That is not hypothetical. It is how this project's own Table III came to hold
numbers from two runs at once, and the only reason it was caught is that somebody
re-derived the numbers by hand. So every per-app file records the id of the run
that wrote it, the directory carries a manifest describing that run, and the
consumers refuse to build from a directory where the two disagree.

The manifest is written twice: once at the start with `complete=False`, and once
at the end with `complete=True`. An interrupted run therefore leaves a directory
that positively declares itself unfinished, rather than one that is merely missing
something nobody thought to check.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

import qnetbench

MANIFEST_NAME = "manifest.json"


class RunConsistencyError(RuntimeError):
    """A data directory does not hold exactly one complete characterization run."""


class RunManifest(BaseModel):
    """What produced the data in one output directory."""

    run_id: str
    generated_at: str
    qnetbench_version: str
    git_commit: str | None = None
    git_dirty: bool | None = None  # None when the commit could not be determined
    seeds: int = 0
    apps: list[str] = []
    complete: bool = False


def new_run_id() -> str:
    return uuid.uuid4().hex


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            cwd=Path(__file__).resolve().parent,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def git_state() -> tuple[str | None, bool | None]:
    """(commit, dirty). Both None outside a git checkout — the data is still usable,
    it just cannot be tied back to a revision."""
    commit = _git("rev-parse", "HEAD")
    if commit is None:
        return None, None
    status = _git("status", "--porcelain")
    return commit, bool(status) if status is not None else None


def start_run(out_dir: Path, apps: list[str], seeds: int) -> RunManifest:
    """Stamp a directory as belonging to a new, not-yet-finished run."""
    commit, dirty = git_state()
    manifest = RunManifest(
        run_id=new_run_id(),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        qnetbench_version=qnetbench.__version__,
        git_commit=commit,
        git_dirty=dirty,
        seeds=seeds,
        apps=list(apps),
        complete=False,
    )
    write_manifest(out_dir, manifest)
    return manifest


def finish_run(out_dir: Path, manifest: RunManifest) -> None:
    write_manifest(out_dir, manifest.model_copy(update={"complete": True}))


def write_manifest(out_dir: Path, manifest: RunManifest) -> None:
    write_atomic(out_dir / MANIFEST_NAME, manifest.model_dump_json(indent=2) + "\n")


def write_atomic(path: Path, text: str) -> None:
    """Write via a temporary file in the same directory, then rename.

    A plain `>` redirect truncates its target the moment the shell opens it, so a
    run that dies before printing leaves an empty file where a reader expects a
    table. Renaming into place means the file is either the previous contents or
    the new ones, never a half-written state.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def load_manifest(out_dir: Path) -> RunManifest:
    path = Path(out_dir) / MANIFEST_NAME
    if not path.exists():
        raise RunConsistencyError(
            f"{path} not found: this directory predates run manifests, or was not "
            f"written by `qnetbench characterize --out`. Regenerate it with "
            f"`qnetbench characterize --out {out_dir}`."
        )
    return RunManifest.model_validate_json(path.read_text())


def app_files(out_dir: Path) -> list[Path]:
    """The per-app signature files in a directory, manifest excluded."""
    return sorted(p for p in Path(out_dir).glob("*.json") if p.name != MANIFEST_NAME)


def verify_run(out_dir: Path) -> RunManifest:
    """Check that a directory holds exactly one complete run, and return its manifest.

    Raises RunConsistencyError describing the specific failure, because the useful
    thing to tell somebody whose figure is about to be wrong is which files came
    from where.
    """
    out_dir = Path(out_dir)
    manifest = load_manifest(out_dir)
    files = app_files(out_dir)

    foreign: dict[str, list[str]] = {}
    for path in files:
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise RunConsistencyError(f"{path} is not readable JSON: {exc}") from exc
        run_id = payload.get("run_id")
        if run_id != manifest.run_id:
            foreign.setdefault(str(run_id), []).append(path.stem)
    if foreign:
        detail = "; ".join(
            f"{len(names)} file(s) "
            + ("unstamped (written before run manifests)" if rid == "None" else f"from run {rid}")
            + f": {', '.join(sorted(names)[:6])}{'...' if len(names) > 6 else ''}"
            for rid, names in foreign.items()
        )
        raise RunConsistencyError(
            f"{out_dir} does not hold a single characterization run. Manifest says "
            f"{manifest.run_id}, but {detail}. Regenerate the whole directory in one "
            f"run: `qnetbench characterize --out {out_dir}`."
        )

    present = {p.stem for p in files}
    missing = [a for a in manifest.apps if a not in present]
    if not manifest.complete or missing:
        raise RunConsistencyError(
            f"{out_dir} holds an unfinished run ({len(present)}/{len(manifest.apps)} apps"
            + (f", missing {', '.join(missing[:6])}" if missing else "")
            + "). Re-run `qnetbench characterize --out "
            + f"{out_dir}` to completion before building anything from it."
        )
    return manifest
