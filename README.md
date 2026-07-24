# qnetbench

A benchmark suite and workload-characterization framework for **quantum-network
applications** — a SPEC/TPC/YCSB-equivalent for the quantum internet.

Every quantum-network scheduler, router, and API in the literature is evaluated on
an idiosyncratic workload (typically QKD plus one hand-rolled protocol), which
makes results incomparable and lets weak abstractions hide. qnetbench provides a
shared, characterized, cross-simulator workload so that these systems can finally
be compared on the same ground. See [docs/issue-4.md](docs/issue-4.md) for the
founding problem statement and [docs/design.md](docs/design.md) for the full
design and roadmap.

> **Status: Phase 5.** Runnable end-to-end on **three backends** (reference,
> **SeQUeNCe**, **NetSquid**) with **six applications** spanning every
> demand-signature class, the portable API, demand-signature characterization, and
> a **versioned, machine-readable trace + metric spec** with **published reference
> traces** ([docs/specs/](docs/specs/), [traces/](traces/)). Deliverables 1 ✔
> (≥2 sims, 6–8 apps), 2 ✔ (characterization), 3 ✔ (spec + traces). Next: the
> cross-policy ranking-inversion result ([docs/design.md §11](docs/design.md)).

## The two ideas

1. **Write an application once, run it on any backend.** Applications program
   against a small portable API (`qnetbench.api`) — classical sockets, EPR
   sockets, local qubit ops — and never import a simulator. Backends adapt that
   API to a simulator (or, here, to a dependency-free reference engine).

2. **Demand is declarative.** Every request for entanglement carries a *contract*
   — minimum fidelity, latency budget / deadline, staleness tolerance, priority.
   Schedulers read it; the trace records requested-vs-delivered against it; the
   characterizer mines its distribution. This is what makes the suite
   *discriminative* rather than merely runnable.

## Install

```bash
pip install -e ".[dev]"          # core + test/lint tooling
```

Core dependencies are just `pydantic` and `numpy`; the reference backend needs
nothing else, so the whole suite runs and tests in CI without any simulator.

## Backends & environments

Applications are written **once** against the portable API and never import a
simulator. You choose the physics by naming a backend — the simulator is imported
lazily behind an optional extra:

```bash
qnetbench run qkd --backend reference   # pure-Python, no simulator needed
qnetbench run qkd --backend sequence    # entanglement supplied by SeQUeNCe
qnetbench run qkd --backend netsquid    # entanglement supplied by NetSquid
```

Install the extra for the simulator you want:

| Backend | Install | Notes |
|---|---|---|
| `reference` | `pip install qnetbench` | Always available. |
| `sequence` | `pip install "qnetbench[sequence]"` | Pulls SeQUeNCe from PyPI. Requires **numpy ≥ 2.3.5**. |
| `netsquid` | register at [netsquid.org](https://netsquid.org), then<br>`pip install --extra-index-url https://pypi.netsquid.org "qnetbench[netsquid]"` | NetSquid ships from its own index (free registration). Requires **numpy < 2**. |

> ⚠️ **SeQUeNCe and NetSquid cannot live in the same environment.** SeQUeNCe pins
> `numpy ≥ 2.3.5` and NetSquid pins `numpy < 2`, so the two extras conflict. Use a
> **separate virtualenv per simulator** (e.g. `.venv` for SeQUeNCe, `.venv-ns` for
> NetSquid). This incompatibility is inherent to the simulators — and is precisely
> the kind of fragmentation this suite exists to paper over: the same applications,
> traces, and metrics run unchanged across otherwise-incompatible tools, because
> only the backend swaps.

Within a given environment you can of course still `import sequence` / `import
netsquid` directly; qnetbench just spares you from writing to their APIs.

## Use it

```bash
qnetbench list                              # available apps and policies
qnetbench run qkd                           # run and print the standard report
qnetbench run qkd --backend sequence        # supply entanglement from SeQUeNCe
qnetbench run bqc --arbitration policy:edf  # apply a scheduling policy
qnetbench run distributed_gate --out run.jsonl   # also write the JSONL trace
qnetbench run qkd --json                    # machine-readable report
```

```python
from qnetbench.harness import run_once
from qnetbench.metrics import compute_report, render

events = run_once("distributed_gate", seed=0)   # a list of trace events
print(render(compute_report(events)))
```

## The applications

| App | Class | Demand signature |
|---|---|---|
| `qkd` | key distribution (E91/BBM92) | steady, rate-hungry, fidelity-thresholded |
| `bqc` | universal blind quantum computation | bursty, latency-coupled, classical-heavy, high-fidelity |
| `distributed_gate` | distributed gate (teleported CNOT) | deadline-critical, staleness-intolerant |
| `chsh` | device-independent QKD (CHSH test) | correlation-quality-sensitive |
| `clock_sync` | sensing (entanglement phase estimation) | steady, correlation-quality-sensitive |
| `anonymous_transmission` | multipartite broadcast (GHZ) | multipartite, GHZ-demand |

Each is physically real: QKD sifts and estimates QBER, BQC delegates a verifiable
blind computation, the distributed gate reproduces the CNOT truth table, CHSH
reaches S ≈ 2√2, clock-sync recovers the phase offset, and anonymous transmission
recovers the broadcast bit from GHZ parity — all exact at fidelity 1.0 and
degrading as fidelity drops, on every backend.

## Characterization

`qnetbench characterize` measures each application's **demand signature** — the
quantities that make workloads discriminative — and prints a cross-application
table (add `--out DIR` to also write per-app signature + curve JSON, so figures
regenerate from source):

```bash
qnetbench characterize            # all apps
qnetbench characterize qkd --out sig/
```

```
app                      parties     cv   fano  msg/pair deadline  F½util  stale½(ms)
------------------------------------------------------------------------------------
anonymous_transmission         3   1.10   0.35      2.02     0.00       —           —
bqc                            2   0.14   0.60      2.00     1.00       —           —
chsh                           2   0.94   0.84      0.01     0.00   0.908        0.23
distributed_gate               2   0.34   0.60      2.25     1.00       —        1.43
qkd                            2   0.94   0.84      0.02     0.00   0.851        0.35
```

The signature spans burstiness (`cv`, `fano`), classical-communication coupling
(`msg/pair`), deadline-criticality (`deadline`), multipartiteness (`parties`),
the fidelity at which utility falls to half its maximum (`F½util`), and the pair
age at which utility halves (`stale½` — the staleness-tolerance curve, feeding the
scheduler/staleness work). Coupled apps (BQC, distributed gate, anonymous) and
fidelity-thresholded ones (QKD, CHSH) separate cleanly.

## Arbitration modes

Borrowing MQT Bench's "pick your level" model, arbitration is a run-level choice:

- `native` — the backend's own default scheduling (the opt-out; what most papers
  run today).
- `policy:<name>` — a backend-agnostic arbiter applies a chosen policy
  (`fifo`, `fidelity_first`, `edf`) identically on every backend.

In Phase 0's single-tenant workloads there is no contention, so the arbiter is
pass-through; the ranking-inversion demonstration under multi-tenant contention
is Phase 6.

## Layout

```
qnetbench/
  api/         portable shim (the frozen contract applications program against)
  trace/       versioned JSONL event schema + I/O (the frozen wire contract)
  apps/        qkd, bqc, distributed_gate, chsh, clock_sync, anonymous — written once
  backends/    reference (pure-Python); replay base + sequence (SeQUeNCe) + netsquid
  policies/    fifo, fidelity_first, edf + the arbitration seam
  metrics/     traces → standard report
  characterize/ demand-signature extraction (single-trace + fidelity/staleness curves)
  topology.py  network + link model
  harness/     run(app × backend × policy × topology) and the CLI
  spec.py      versioned JSON Schemas + reference-corpus generator
tests/         statevector physics, cross-backend invariants, trace round-trip
docs/          design.md (architecture + roadmap), issue-4.md, specs/ (versioned spec)
traces/        published reference traces (one per app) + checksummed manifest
```

## Develop

```bash
pytest            # physics, app invariants, trace round-trip, policies, metrics
ruff check qnetbench tests
mypy qnetbench    # strict
```

## License

Apache-2.0.

## AI usage

Note that both Fable 5 and Opus 4.8 were used to help in the development of this library. 
