# qnetbench

A benchmark suite and workload-characterization framework for **quantum-network
applications** for the quantum internet.

**27 core protocols + a 66-entry catalog** (unbounded via a circuit generator), on
**3 backends** (reference, SeQUeNCe, NetSquid). New here? See **[docs/usage.md](docs/usage.md)** —
how to run benchmarks, what data you get, how to use different topologies, and what
you can define vs. what ships predefined.

## Install

```bash
pip install -e ".[dev]"          # core + test/lint tooling
```

Core dependencies are just `pydantic` and `numpy`; the reference backend needs
nothing else, so the whole suite runs and tests in CI without any simulator.

## Backends & environments

Applications are written **once** against the portable API and never import a
simulator. You choose the backend and the relevant simulator is imported
lazily behind:

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
> NetSquid). This incompatibility is inherent to the simulators, and is 
> the kind of fragmentation this suite exists to paper over. ⚠️

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
| `bb84` | prepare-and-measure BB84 | single-qubit **transmission** (no shared pairs), fidelity-thresholded |
| `b92` | prepare-and-measure B92 (two non-orthogonal states) | single-qubit **transmission**, lower sifting yield, fidelity-thresholded |
| `six_state` | prepare-and-measure six-state QKD (three bases) | single-qubit **transmission**, higher QBER tolerance, lower yield |
| `bqc` | universal blind quantum computation | bursty, latency-coupled, classical-heavy, high-fidelity |
| `verified_bqc` | verified BQC (trap-based) | like BQC + trap overhead; accept/reject verification |
| `distributed_gate` | distributed gate (teleported CNOT) | deadline-critical, staleness-intolerant |
| `teleportation` | quantum state teleportation | steady, latency-coupled, high-fidelity |
| `heralded_teleport` | teleportation over a probabilistic (heralded) BSM | **on/off duty cycle** — the only super-Poissonian app (Fano 2.10); geometric retry bursts |
| `distillation` | entanglement distillation (BBPSSW/DEJMPS) | **produces** entanglement — rate-hungry, deliberately *low* `min_fidelity`, staleness-critical |
| `distilled_gate` | distil-then-consume distributed gate | **mixed criticality** — the only app emitting both best-effort and deadline demand (fraction 0.08) |
| `position_verification` | quantum position verification (distance bounding) | deadline set by **physics** (propagation bound) — a late pair is insecure, not slow |
| `oblivious_transfer` | 1-out-of-2 quantum OT (BBCS) | secure two-party computation; single-qubit **transmission**, lowest classical coupling in the suite |
| `chsh` | device-independent QKD (CHSH test) | correlation-quality-sensitive |
| `clock_sync` | sensing (entanglement phase estimation) | steady, correlation-quality-sensitive |
| `anonymous_transmission` | multipartite broadcast (GHZ) | multipartite, GHZ-demand |
| `byzantine_agreement` | detectable broadcast / Byzantine agreement (GHZ) | 3-party GHZ, bursty (2 pairs/round), consensus / fault-detection |
| `secret_sharing` | (n,n) quantum secret sharing (GHZ) | multipartite, threshold reconstruction |
| `threshold_secret_sharing` | ((3,5)) threshold QSS (five-qubit code) | 5-party single-qubit **transmission**; any 3 reconstruct, any 2 learn nothing |
| `conference_key` | conference key agreement (4-party GHZ) | 4-party GHZ, highly fidelity-demanding |
| `leader_election` | fair leader election (5-party GHZ) | 5-party — highest party count, the most fidelity-demanding app |
| `entanglement_swap` | entanglement swapping (repeater line) | multi-hop / relay — two elementary pairs per end-to-end unit |
| `multihop_qkd` | QKD over a repeater chain | multi-hop **and** steady, fidelity-thresholded (QBER compounds both hops) |
| `shared_randomness` | shared randomness from measured pairs | steady, rate-hungry, `purpose="measure"` (measured on delivery) |
| `dqc_ghz4`, `dqc_qft4`, `dqc_random4` | distributed circuits (teleported gates) | demand **derived from real circuits** — bursty, deadline-critical |

The table above is the **core** — distinct protocols that CI, the reference corpus,
and the cross-backend equivalence suite all iterate. Beyond it is a **catalog** of
50+ parameterized benchmarks (`qnetbench list --all`, run any by name), generated
mostly as DQC over a family of distributed circuits at a range of sizes:

```bash
qnetbench list --all          # the full catalog (50+)
qnetbench run dqc_qft8        # any catalog entry, on demand
```

The DQC benchmarks come from [`qnetbench.circuits`](qnetbench/circuits.py): a
distributed-circuit IR whose non-local gates compile to teleported gates, so each
circuit's structure becomes an *Entanglement Demand Schedule*. Built-in families
(GHZ, QFT, random, graph state, IQP, hardware-efficient ansatz) are mirror circuits
(`U;U†`) verified by returning to |0…0>; an optional loader (`from_qiskit`,
`pip install "qnetbench[mqt]"`) turns MQT Bench / Qiskit circuits into demand. This
is the SPEC / MQT Bench model: a curated core, and a generator for the long tail.

## Characterization

`qnetbench characterize` measures each application's **demand signature** and prints a cross-application
table (add `--out DIR` to also write per-app signature + curve JSON, so figures
regenerate from source):

```bash
qnetbench characterize            # all apps
qnetbench characterize qkd --out sig/
```

```
app                      parties     cv   fano  msg/pair deadline  F½util  stale½(ms)
-------------------------------------------------------------------------------------
anonymous_transmission         3   1.10   0.35      2.02     0.00       —           —
bb84                           2   0.00   0.01      0.02     0.00   0.788           —
bqc                            2   0.14   0.60      2.00     1.00       —           —
chsh                           2   0.94   0.84      0.01     0.00   0.908        0.23
conference_key                 4   1.54   0.53      2.02     0.00   0.952        0.14
distributed_gate               2   0.34   0.60      2.25     1.00       —        1.43
dqc_ghz4                       2   0.16   0.70      2.33     1.00   0.525        0.83
dqc_qft4                       2   0.24   0.20      2.12     1.00   0.900        0.18
dqc_random4                    2   0.25   0.20      2.10     1.00   0.725        0.40
entanglement_swap              3   0.48   0.21      1.52     0.00       —           —
leader_election                5   1.83   0.27      2.01     0.00   0.974        0.10
multihop_qkd                   3   1.12   0.25      0.54     0.00   0.866        0.10
qkd                            2   0.94   0.84      0.02     0.00   0.851        0.35
secret_sharing                 3   1.10   0.35      2.02     0.00       —           —
shared_randomness              2   0.92   0.99      0.02     0.00       —           —
teleportation                  2   0.55   0.27      1.02     1.00       —           —
verified_bqc                   2   0.24   0.20      2.00     1.00       —           —
```

The signature spans burstiness (`cv`, `fano`), classical-communication coupling
(`msg/pair`), deadline-criticality (`deadline`), multipartiteness (`parties`),
the fidelity at which utility falls to half its maximum (`F½util`), and the pair
age at which utility halves (`stale½` — the staleness-tolerance curve, feeding the
scheduler/staleness work). Coupled apps (BQC, distributed gate, anonymous) and
fidelity-thresholded ones (QKD, CHSH) separate cleanly.

## Arbitration modes

Borrowing MQT Bench's "pick your level" model, arbitration is a run-level choice:

- `native`: the backend's own default scheduling (the opt-out; what most papers
  run today).
- `policy:<name>`: a backend-agnostic arbiter applies a chosen policy
  (`fifo`, `fidelity_first`, `edf`) identically on every backend.

## Cross-policy evaluation — the ranking inverts

The point of a benchmark suite is to show that **single-workload evaluation is
unreliable**. `qnetbench contention` runs several tenants (parameterized by real
applications' demand contracts) competing for one link whose entanglement supply
is below aggregate demand, under three published scheduling policies:

```bash
qnetbench contention
```

```
policy              deadline_heavy    fidelity_heavy
----------------------------------------------------
fifo                       0.150             0.433
fidelity_first             0.150             0.533*
edf                        0.367*            0.367
winner                         edf    fidelity_first
```

**EDF wins on deadline-heavy traffic and is *last* on fidelity-heavy traffic;
fidelity_first does the exact opposite.** The best policy flips across workload
classes, so a paper that evaluated on either workload alone would have crowned one
policy and been wrong about the other. That inversion is the suite's reason to
exist.

## Layout

```
qnetbench/
  api/         portable shim (the frozen contract applications program against)
  trace/       versioned JSONL event schema + I/O (the frozen wire contract)
  apps/        27 core protocols (qkd, bb84, b92, six_state, bqc, byzantine_agreement, …)
  circuits.py  distributed-circuit IR + families (GHZ/QFT/random/graph/IQP/HEA) + Qiskit loader
               (the core + circuits form a catalog of 50+ via `qnetbench list --all`)
  backends/    reference (pure-Python); replay base + sequence (SeQUeNCe) + netsquid
  policies/    fifo, fidelity_first, edf + the arbitration seam
  metrics/     traces → standard report
  characterize/ demand-signature extraction (single-trace + fidelity/staleness curves)
  contention.py multi-tenant scheduling: the cross-policy ranking-inversion result
  topology.py  network + link model
  harness/     run(app × backend × policy × topology) and the CLI
  spec.py      versioned JSON Schemas + reference-corpus generator
tests/         statevector physics, cross-backend invariants, trace round-trip
docs/          usage.md (how to use), adopting.md (extend), design.md (+ TODO), specs/
scripts/       plot_curves.py (characterization figures)
traces/        published reference traces (one per app) + checksummed manifest
```

## Contributing to the suite

Instructions on how to extend the suite are documented in [docs/adopting.md](docs/adopting.md):

- **Add an application**: one file against the portable API (a complete `Ping`
  example runs on every backend).
- **Add a backend**: a ~1-method `ReplayBackend` subclass returning a delivered-pair
  supply.
- **Consume traces**: read the JSONL in any language; the schema is the versioned
  contract in [docs/specs/](docs/specs/).

## Develop

```bash
pytest            # physics, app invariants, trace round-trip, policies, metrics, contention
ruff check qnetbench tests
mypy qnetbench    # strict
```
The SeQUeNCe and NetSquid backends have conflicting numpy pins, so run the suite in
one virtualenv per simulator (see [Backends & environments](#backends--environments));
each shows the reference tests plus its own simulator's, skipping the other's.

## License

Apache-2.0.

## AI usage

Note that both Fable 5 and Opus 4.8 were used to help in the development of this library. 
The commits they have contributed to are saved accordingly in the commit history.