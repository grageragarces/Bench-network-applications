# Characterization

A single run tells you how one application did on one link. The **demand
signature** tells you what kind of load that application places on a network — and
that is what makes two workloads comparable, and what makes a scheduling claim
testable.

```bash
qnetbench characterize qkd              # one application
qnetbench characterize                  # all 27 core applications
qnetbench characterize --out sig/       # + per-app curve JSON, tables, provenance
```

## The axes

Four are read from a single trace; two require parameter sweeps.

### From one trace

| Axis | Field | Meaning |
|---|---|---|
| Burstiness | `request_cv`, `fano_factor` | coefficient of variation of demand inter-arrivals, and the index of dispersion of counts per bin. Fano 1.0 is Poisson, above is bursty, below is more regular |
| Classical coupling | `msgs_per_pair`, `bytes_per_pair` | how much classical traffic each delivered pair drags with it |
| Deadline-criticality | `deadline_fraction`, `min_latency_budget` | the fraction of requests carrying a deadline or budget, and the tightest one |
| Multipartiteness | `n_parties` | how many nodes the demand spans |
| Staleness intolerance | `min_staleness_tolerance` | the tightest tolerated pair age declared in a contract |

### From sweeps

| Axis | Field | Meaning |
|---|---|---|
| Fidelity sensitivity | `fidelity_threshold` (F½util) | delivered fidelity at which utility falls to half its swept range |
| Staleness tolerance | `staleness_halflife` (stale½) | pair age at which utility halves |

Both sweeps run on the reference backend, which is deterministic, fast, and the
only one that models pair aging.

## The cross-application table

```console
$ qnetbench characterize
app                      parties     cv   fano  msg/pair  B/pair deadline   F½util (±std)     ΔF   stale½(ms, ±std) stale½r(ms)
-------------------------------------------------------------------------------------------------------------------------------
bqc                            2   0.49   0.60      2.00    2.00     1.00     0.778±0.116   0.16                  —       0.516
chsh                           2   0.95   0.87      0.01    4.00     0.00     0.884±0.036   0.89        0.170±0.076       0.170
conference_key                 4   1.52   0.43      2.02    2.03     0.00     0.976±0.027   0.83        0.051±0.020       0.046
distributed_gate               2   0.49   0.60      2.25    5.00     1.00     0.743±0.116   0.35        2.906±0.888       0.590
heralded_teleport              2   1.51   2.20      1.67    2.67     0.00     0.764±0.081   0.34        4.288±1.325       0.608
leader_election                5   1.84   0.60      2.01    2.03     0.00     0.992±0.007   1.00        0.010±0.012       0.010
qkd                            2   0.95   0.87      0.02    2.45     0.00     0.838±0.053   0.25        0.246±0.104       0.246
~ = the mean curve does not cross; value is the median over the (crossing/total) seeds that do.
```

(Seven of the 27 rows, for space.) The classes separate cleanly and without being
told to: `heralded_teleport` is the only super-Poissonian application (Fano 2.20),
coupled applications sit at ~2 messages per pair while QKD sits at 0.02,
`leader_election` is both the most multipartite and the most fidelity-demanding,
and `bqc` and `distributed_gate` are the deadline-driven ones.

## Reading the uncertainty columns

The characterization reports how *well resolved* each crossing is, not just where
it is. This matters more than it sounds: on a coarse sweep, a crossing inside the
first staleness interval was once reported as 0.10 ms ± 0.00 when all the data
supported was "somewhere between 0 and 0.2 ms".

| Column | What it is |
|---|---|
| `±std` | spread across seeds of the crossing point itself — not of the utility values that produced it |
| bracket | width of the interval the crossing was finally bisected into; this is the *resolution*, and it is often the larger error |
| `ΔF` | utility gained across the swept fidelity range, `u(F_max) - u(F_min)`. A near-zero ΔF is what "fidelity-insensitive" actually means — a threshold alone cannot say it |
| `stale½r` | the half-life measured from the curve's own asymptotic floor rather than from zero |
| `~` and `(k/n)` | the mean curve never crosses; the value is the median over the k of n seeds that do |

Both staleness figures are reported rather than one being chosen: the absolute
half-life is the operationally meaningful one ("when has half the value gone?"),
and the gap between the two is the honest measure of how well it is resolved.

## From Python

```python
from qnetbench.characterize import characterize_app, characterize_trace, render_table
from qnetbench.harness import run_once

# The full signature: one trace + both sweeps.
signature, curves = characterize_app("qkd", seeds=range(8))
print(signature.trace.request_cv, signature.fidelity_threshold)
print(render_table([signature]))

# Just the single-trace axes — cheap, no sweeps.
sig = characterize_trace(run_once("bqc", seed=0))
print(sig.msgs_per_pair, sig.deadline_fraction, sig.n_parties)

# The raw curves, for plotting.
curves.fidelity.as_rows()[:3]
```

`characterize_app` resolves applications by name, so it works on anything you
[registered](running.md#running-a-benchmark-you-built-yourself) — including a
benchmark built from your own circuit.

## Output files

`--out DIR` writes machine-readable results so that figures regenerate from source
rather than being transcribed:

| File | Contents |
|---|---|
| `<app>.json` | the signature plus both curves as rows, tagged with the run id |
| `table.txt` | the rendered cross-application table |
| `table.tex` | the same table as a booktabs `tabular`, for `\input{}` |
| `manifest.json` | run id, app list, seed count, qnetbench version, git commit and dirty flag |

```bash
qnetbench characterize --out sig/
python scripts/plot_curves.py sig/        # -> curves.png  (needs the viz extra)
```

## Provenance

The manifest is written **before** the run and finished after it, so a run that
dies half way leaves a directory that says so rather than one that looks complete.
Tables are written by the tool rather than by a shell redirect, because `>
table.txt` truncates at launch and an interrupted run would leave an empty file
where a reader expects a table.

```python
from qnetbench.characterize import verify_run
manifest = verify_run("sig/")   # raises RunConsistencyError on a partial or mixed run
```

Every per-app JSON carries the `run_id`, so files from two different runs cannot be
silently mixed into one figure.

## Cost

Characterizing all 27 applications sweeps fidelity and pair age at 32 seeds per
point, with bisection refinement around each crossing. That is minutes, not
seconds. Use `--seeds 4` while iterating and the default for anything you publish —
the seed count was raised from 8 precisely because refinement removed grid
resolution as the limiting error and exposed seed noise underneath it.

## API

[`characterize_app`, `characterize_trace`, `characterize_curves`, `AppSignature`,
`TraceSignature`, `Curve`, `render_table`, `render_latex`, `verify_run`](../reference/characterize.md).
