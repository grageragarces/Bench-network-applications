# Changelog

All notable changes to `qnetbench` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/) — with the caveat below.

## Three version numbers, on purpose

The package version is **not** the same as the two contract versions, and they move
independently:

| Version | Where | What it promises |
|---|---|---|
| package (`qnetbench.__version__`, `pyproject.toml`) | the distribution | the usual semver promise about the Python API |
| `API_VERSION` (`qnetbench.api`) | the portable shim | the surface an application programs against |
| `SCHEMA_VERSION` / `SPEC_VERSION` (`qnetbench.trace`, `qnetbench.spec`) | the JSONL wire format | the contract a third-party trace consumer depends on |

A package release may leave both contracts untouched, and usually should. The
contract versions travel in the data — every trace's `run_header` carries both — so
a consumer checks compatibility from the file rather than from this document.

---

## [0.1.0] — unreleased

First release with the characterization made publication-grade, and the first that
changes published data rather than only adding to it.

Contracts unchanged: `API_VERSION` and `SCHEMA_VERSION` both stay at **0.2.0**.
`qnetbench/api/` and `qnetbench/trace/` are untouched since 0.0.2, and the JSON
Schemas in `docs/specs/` are byte-identical.

### Changed — read this before comparing numbers to 0.0.2

- **The published reference corpus was regenerated.** The backend constructor gave
  link sampling and quantum measurement a *single* RNG stream (and every replay
  backend inherits it), so a backend replaying a pre-generated supply — which draws
  no link samples at all — landed at a different position in that stream than the
  reference backend did, and measurement outcomes stopped being comparable across
  backends at a fixed seed. The two streams are now spawned separately. That
  changed outcomes, and therefore every trace in `traces/` — same schema version,
  different data. Compare `sha256` values in
  `traces/manifest.json` if you have 0.0.2 artifacts to reconcile. Replay is now
  outcome-preserving, which is what makes cross-backend equivalence testable.
- **Characterization crossings are refined by bisection** rather than read off a
  coarse grid, and the default seed count rose from 8 to 32. Reported crossings now
  come with a resolution (the bracket width they were located in) alongside the
  seed spread — on the old grid, a crossing inside the first staleness interval was
  reported as 0.10 ms ± 0.00 when the data only supported "somewhere in (0, 0.2) ms".
  Figures and tables regenerated from 0.0.2 data will differ.
- **Contention tenants replay real arrival patterns.** Each tenant now carries the
  measured inter-arrival shape of its application (normalised to mean 1.0) and an
  independent start phase, instead of issuing on a fixed cadence from `t = 0`.
  Previously, several tenants of one application were one stream counted several
  times — a thundering herd that maximised queueing by construction and left a
  fidelity-ordered policy nothing to order by. The headline operating point moved
  with it: `CAPACITY` 110 → 160 pairs/s. **The ranking inversion still holds**, but
  the utility figures are substantially different.
- `qnetbench.__version__` is single-sourced from the installed distribution
  metadata. It was a hardcoded `"0.0.1"` through the 0.0.2 release, which the
  characterization run manifest recorded — making the stale literal a provenance
  defect, not a cosmetic one.

### Added

- **Run provenance for characterization** (`qnetbench.characterize.provenance`):
  `qnetbench characterize --out DIR` now stamps a `manifest.json` *before* the run
  and finishes it after, so a run that dies half way leaves a directory that says
  so rather than one that looks complete. Records a run id, the app list, seed
  count, the qnetbench version, and the git commit plus dirty flag. `verify_run()`
  raises `RunConsistencyError` on a partial or mixed-run directory. Tables are
  written by the tool rather than by a shell redirect, since `> table.txt`
  truncates at launch.
- **`register_app(app, *, replace=False)`** — adds a benchmark built at runtime to
  the catalog under its own name, so everything name-addressed resolves it
  (`get_app`, `run_once`, `characterize_app`, `catalog_apps()`). This is what lets a
  circuit you loaded or generated reach the harness and the characterizer instead of
  only the low-level backend.
- **Uncertainty and diagnostics on every signature**: per-seed crossing spread,
  bracket width, the utility range across the swept fidelities (`ΔF` — a near-zero
  range is what "fidelity-insensitive" actually means, which a threshold alone
  cannot express), a staleness half-life measured from the curve's own asymptotic
  floor, and the median plus count of per-seed crossings for curves whose mean
  never crosses.
- `qnetbench characterize --latex` emits the cross-application table as a booktabs
  `tabular`, also always written to `--out/table.tex`, so a manuscript `\input{}`s
  the table instead of transcribing it.
- `burstiness_mixes()` — two contention mixes differing in *nothing but arrival
  shape*, isolating the burstiness axis that a fixed-cadence model cannot express.
- `winning_policies()` and `has_inversion()` — several operating points have two or
  three policies tied on exactly the same score, and an argmax silently turns a tie
  into a winner.
- **Documentation site** (`mkdocs.yml`, `docs/`): install and quickstart, a page per
  utility, a tutorial on loading any distributed circuit (built-in families,
  hand-written circuits, Qiskit / MQT Bench imports), and an API reference generated
  from the package docstrings. `pip install "qnetbench[docs]"`, then `mkdocs serve`.

### Fixed

- The replay-backend RNG stream bug described under **Changed** above.
- Stale references in `docs/adopting.md` (`_REGISTRY` → `_CORE`; "all six
  applications" → all 27 core applications).

---

## [0.0.2] — 2026-08-06

The suite as it stood for the first substantive PyPI upload: **27 core protocols, a
66-entry catalog**, three backends, four arbitration modes.

### Added

- Prepare-and-measure protocols and the single-qubit transmission primitive
  (`Host.qsend` / `Host.qrecv`), which moved both contracts to **0.2.0** and added
  the `qubit_sent` trace event: BB84, B92, six-state QKD, oblivious transfer,
  ((3,5)) threshold quantum secret sharing.
- Protocols closing measured gaps in the demand space: heralded teleportation (the
  only super-Poissonian workload), distillation, distil-then-consume gates (mixed
  criticality), position verification (a deadline set by physics), Byzantine
  agreement, leader election, conference key agreement, multi-hop QKD, and others.
- Full-catalog CI coverage — every one of the 66 entries runs noiselessly in CI —
  plus `scripts/plot_curves.py` and the `usage.md` guide.

### Note

`qnetbench.__version__` reported `"0.0.1"` in this release; the distribution
metadata was correct. Fixed in 0.1.0.

---

## [0.0.1]

Name reservation on PyPI.
