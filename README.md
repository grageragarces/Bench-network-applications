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

> **Status: Phase 2.** Runnable end-to-end on **three backends** — the built-in
> reference engine, **SeQUeNCe**, and **NetSquid** — with the portable API, the
> versioned trace format, three applications spanning three demand signatures, the
> metric suite, and the arbitration seam. Cross-backend equivalence tests pass on
> both simulators (Deliverable 1 ✔ ≥2 sims). The full 6–8 application set,
> demand-signature characterization, and the cross-policy ranking-inversion result
> are later phases ([docs/design.md §11](docs/design.md)).

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

## The three Phase-0 applications

| App | Class | Demand signature |
|---|---|---|
| `qkd` | key distribution (E91/BBM92) | steady, rate-hungry, fidelity-thresholded |
| `bqc` | universal blind quantum computation | bursty, latency-coupled, classical-heavy, high-fidelity |
| `distributed_gate` | teleported CNOT | deadline-critical, staleness-intolerant |

Each is physically real on the reference backend: QKD sifts and estimates QBER,
BQC delegates a verifiable blind computation, and the distributed gate reproduces
the CNOT truth table (all exact at fidelity 1.0, degrading as fidelity drops).

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
  apps/        qkd, bqc, distributed_gate — written once, backend-agnostic
  backends/    reference (pure-Python); replay base + sequence (SeQUeNCe) + netsquid
  policies/    fifo, fidelity_first, edf + the arbitration seam
  metrics/     traces → standard report
  topology.py  network + link model
  harness/     run(app × backend × policy × topology) and the CLI
tests/         statevector physics, cross-backend invariants, trace round-trip
docs/          design.md (architecture + roadmap), issue-4.md (motivation)
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
