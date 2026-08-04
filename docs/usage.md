# Using qnetbench

A practical guide: how to run benchmarks, what data you get back, how to point them
at different topologies, and what you can define versus what ships predefined.
(To *add* an application or a backend, see [adopting.md](adopting.md).)

## Install

The core (reference backend) needs only `pydantic` + `numpy`:

```bash
pip install qnetbench            # core + reference backend
pip install "qnetbench[dev]"     # + test/lint tooling
```

Simulator backends are optional extras — and, because SeQUeNCe pins `numpy ≥ 2.3.5`
and NetSquid pins `numpy < 2`, **use one virtualenv per simulator**:

```bash
pip install "qnetbench[sequence]"                                   # SeQUeNCe
pip install --extra-index-url https://pypi.netsquid.org "qnetbench[netsquid]"  # NetSquid (register first)
pip install "qnetbench[mqt]"     # optional: load MQT Bench / Qiskit circuits as DQC demand
pip install "qnetbench[viz]"     # optional: scripts/plot_curves.py
```

## How many benchmarks are there?

| Layer | Count | What it is |
|---|---|---|
| Distinct protocols (**core**) | **22** | hand-written protocols spanning every demand class (`qnetbench list`) |
| Predefined runnable **catalog** | **61** | the 22 core + 39 generated DQC instances — `qnetbench list --all` |
| DQC instances in the catalog | 42 | 6 circuit families (GHZ, QFT, random, graph, IQP, HEA) × 7 sizes (4–10); 3 overlap the core |
| **Generatable (unbounded)** | ∞ | any circuit family × any size × any partition, or any MQT Bench / Qiskit circuit |

Each benchmark also runs across **3 backends** × **4 arbitration modes** (native +
`fifo`/`fidelity_first`/`edf`), so the predefined evaluation matrix is already
**61 × 3 × 4 = 732** runnable configurations — before the unbounded circuit generator.

```bash
qnetbench list          # the 22 core protocols + the 3 policies
qnetbench list --all    # the full 61-entry catalog
```

## Run one benchmark

```bash
qnetbench run qkd                       # print the standard report
qnetbench run dqc_qft8 --backend sequence   # any catalog entry, on any backend
qnetbench run bqc --arbitration policy:edf  # apply a scheduling policy
qnetbench run qkd --out run.jsonl           # also write the JSONL trace
qnetbench run qkd --json                     # machine-readable report
```

```python
from qnetbench.harness import run_once
from qnetbench.metrics import compute_report, render

events = run_once("distributed_gate", seed=0)   # -> list of trace events
print(render(compute_report(events)))
```

## What information you get

**The report** (`compute_report(events)` → a `Report`) — delivered-pair rate and
mean fidelity, fidelity-weighted throughput, per-`kind` contract-violation rate,
latency percentiles (p50/p95/p99), classical-coupling (bytes & msgs per pair),
`qubits_sent` (for prepare-and-measure apps), and the per-role `success`/`utility`
plus the aggregate `app_success`/`app_utility`.

**The trace** — one JSON object per line (JSONL), the versioned wire contract in
[specs/](specs/): `run_header`, `ent_requested` (carries the `demand`),
`ent_delivered`, `contract_violation`, `classical_msg`, `qubit_sent`, `measurement`,
`app_outcome`. Metrics are computed *from* the trace, so any tool can consume it:

```python
import json
for line in open("run.jsonl"):
    e = json.loads(line)
    if e["kind"] == "ent_delivered":
        ...  # e["actual_fidelity"], e["latency"], e["pair_age"]
```

**Published reference traces** for all 22 core apps live in [../traces/](../traces/)
with a checksummed manifest — regenerate with `qnetbench corpus`.

**The demand signature** (`qnetbench characterize`) — burstiness, classical coupling,
deadline-criticality, multipartiteness, and fidelity-sensitivity / staleness-tolerance
curves. Write the curve data and plot it:

```bash
qnetbench characterize --out sig/       # cross-app table + per-app curve JSON
python scripts/plot_curves.py sig/      # -> curves.png
```

**The cross-policy result** (`qnetbench contention`) — the multi-tenant evaluation
that shows the policy ranking inverting across workload classes.

## Topologies — predefined and custom

By default the harness picks a topology from an app's roles: a **direct link** for a
2-role app, or a **star** (`roles[0]` = hub) for a multipartite one. Override it with
the `topology=` argument:

```python
from qnetbench.harness import run_once
from qnetbench.topology import line2, star, LinkModel

# A noisier / faster / longer-coherence link (all fields optional):
link = LinkModel(link_fidelity=0.9, attempt_latency=1e-3, fidelity_std=0.0)
run_once("qkd", topology=line2("alice", "bob", link=link))

# A 4-node star for a multipartite app:
run_once("conference_key", topology=star("hub", ["leaf1", "leaf2", "leaf3"], link=link))
```

A `Topology` is just named nodes plus a per-edge `LinkModel`, so arbitrary graphs are
possible by constructing one directly (Phase-0 backends model direct links and
star/GHZ fusion; general multi-hop routing is on the roadmap).

## What you can define vs. what's predefined

| You can define | Predefined |
|---|---|
| **Topology** — nodes, edges, per-edge `LinkModel` (`link_fidelity`, `attempt_latency`, `fidelity_std`) | `line2`, `star`, and an auto per-app default |
| **Link noise / staleness** — `pair_age` + `coherence_time` on `run_once` (reference backend) | fresh, noiseless-to-Werner link models |
| **Per-run config** — `seed`, `cfg={"rounds": …, "depth": …}` | sensible defaults per app |
| **Backend** — `backend="reference"|"sequence"|"netsquid"` | 3 backends behind extras |
| **Arbitration** — `native` or `policy:<fifo|fidelity_first|edf>` | 3 published policies |
| **Circuits** — any `qnetbench.circuits` family × size × partition, or `from_qiskit` (MQT Bench) | 6 families × 7 sizes = 42 DQC entries |
| **New applications** — one file against the api ([adopting.md](adopting.md)) | 22 core protocols |
| **New backends** — a `ReplayBackend` subclass ([adopting.md](adopting.md)) | reference + SeQUeNCe + NetSquid |

## Reproducibility

Every run is deterministic in its `seed` (per-node seeded RNG), so a `(app, seed,
backend, topology)` tuple reproduces byte-for-byte. The published traces and JSON
Schemas are drift-guarded in CI.
