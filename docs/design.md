# qnetbench — Design & Roadmap

> A benchmark suite and workload-characterization framework for quantum-network
> applications. Answers Issue #4: a SPEC/TPC/YCSB-equivalent for the quantum
> internet, so that schedulers, routers, and APIs can be evaluated on a shared,
> characterized, cross-simulator workload instead of one bespoke toy each.

**Status:** all five deliverables complete, plus a large expansion — **22 core
protocols + a 61-entry catalog** on **3 backends** (reference, SeQUeNCe, NetSquid),
published to GitHub. This document is the architecture + roadmap; the resolved
`[DECIDE]` sections below are kept for the record. **New here? Start with
[usage.md](usage.md)** — how to run benchmarks, what data you get, how to point them
at different topologies, and what you can define vs. what ships predefined. What's
still open is collected in [§14 Remaining work](#14-remaining-work-todo).

---

## 1. Design goals (in priority order)

1. **Write an application once, run it on any backend.** An application must not
   import a simulator. It talks only to the portable API shim. This is the whole
   bet — if the shim leaks simulator concepts, comparability dies.
2. **Demand is first-class and declarative.** Every request for entanglement
   carries a *contract*: minimum fidelity, latency budget / deadline, staleness
   tolerance, priority weight. Schedulers see contracts; metrics measure
   contract violations. This is what makes the suite *discriminative* rather than
   merely runnable, and it is what feeds the demand-signature characterization
   (Deliverable 2) and Issue #5 (staleness).
3. **Everything observable is a trace.** A run emits a versioned, machine-readable
   event stream. Metrics are computed *from traces*, never inline. A scheduler
   paper can consume traces without importing our code, and our own metrics are
   just the first consumer.
4. **Two independent backends or it doesn't count.** A workload spec that only
   runs on one simulator has proven nothing. Cross-backend equivalence tests are
   a first-class deliverable, not an afterthought.
5. **Adoption is the success metric.** Typed schemas, semantic-versioned specs,
   and docs sufficient for a third party to add an application or a backend
   without reading our internals.

### Non-goals

- Not a new simulator. We adapt SeQUeNCe and NetSquid; we do not model physics.
- Not a scheduler. We provide the *policy seam* and evaluate published policies;
  we don't claim to invent a good one.
- Not tied to the Delft stack. SquidASM's `Program` interface is our ergonomic
  reference (it's proven), but the shim is its own thing with backends for
  non-Delft simulators.

---

## 2. Architecture

Seven layers, each depending only on the ones above it:

```
┌─────────────────────────────────────────────────────────────┐
│  qnetbench.cli / harness   run(app × backend × policy × topo)│
├─────────────────────────────────────────────────────────────┤
│  qnetbench.metrics         traces → metrics + curves + report │
│  qnetbench.characterize    demand-signature extraction        │
├─────────────────────────────────────────────────────────────┤
│  qnetbench.trace           versioned event schema (pydantic)  │  ← the contract
├─────────────────────────────────────────────────────────────┤
│  qnetbench.apps            applications, written ONCE          │
├─────────────────────────────────────────────────────────────┤
│  qnetbench.api             the portable shim (ABCs + types)    │  ← the bet
├─────────────────────────────────────────────────────────────┤
│  qnetbench.backends        reference │ sequence │ netsquid     │
│  qnetbench.policies        scheduling/routing plug-in seam     │
└─────────────────────────────────────────────────────────────┘
```

- **`api`** and **`trace`** are the two frozen contracts. They get semantic
  versions and change slowly. Everything else is free to move.
- Applications depend on `api` and emit into `trace`. They never see a backend.
- Backends depend on `api` (they implement it) and `trace` (they emit low-level
  entanglement events). They never see an application.

---

## 3. The portable API shim (`qnetbench.api`) — the crux

Modeled on the SquidASM `Program` interface (classical sockets + EPR sockets +
local qubit ops), extended with **explicit demand contracts**. Concrete sketch:

```python
class Demand(BaseModel):
    """The contract attached to a request for entanglement."""
    min_fidelity: float                 # reject/flag deliveries below this
    latency_budget: Duration | None     # soft deadline from request to delivery
    deadline: SimTime | None            # hard absolute deadline (distributed gates)
    staleness_tolerance: Duration | None # max age of a pre-generated pair still usable
    priority: float = 1.0               # scheduler weight
    purpose: Literal["keep", "measure"] # keep the qubit, or measure immediately

class EPRSocket(Protocol):
    def request(self, n: int, demand: Demand) -> list[EntanglementHandle]: ...
    #   returns handles once delivered (or contract-violation markers)

class ClassicalSocket(Protocol):
    def send(self, msg: bytes) -> None: ...
    def recv(self) -> bytes: ...

class Qubit(Protocol):
    def apply(self, gate: Gate, *params: float) -> None: ...
    def measure(self, basis: Basis = Basis.Z) -> int: ...

class Host(Protocol):
    node: NodeId
    def epr_socket(self, peer: NodeId) -> EPRSocket: ...
    def classical_socket(self, peer: NodeId) -> ClassicalSocket: ...
    def now(self) -> SimTime: ...
    def log(self, event: TraceEvent) -> None: ...   # application-level outcome

class Application(Protocol):
    name: str
    def roles(self) -> list[Role]: ...              # e.g. [Alice, Bob]
    def run(self, host: Host, role: Role, cfg: dict) -> AppOutcome: ...
```

**Why `Demand` is separate from the request call:** it turns every entanglement
request into a labelled, measurable event. The backend's policy layer reads the
`Demand`; the trace records requested-vs-delivered; the characterizer mines the
distribution of demands an application emits. Without this, staleness tolerance
and fidelity/rate sensitivity are unmeasurable — which is exactly the gap the
issue names.

**Async model — RESOLVED: (a) blocking / generator style.** Applications are
naturally concurrent (send, wait, receive). Calls block on generators driven by
the backend's event loop (SquidASM-style yields). This matches both target
simulators' native styles and keeps application code readable and sequential.

---

## 4. Trace format (`qnetbench.trace`) — the frozen wire contract

JSONL, one event per line, each a tagged pydantic model. Semantic-versioned via
a `schema_version` header record. Compact enough to hand to a scheduler paper.

Core event types:

| Event | Emitted by | Key fields |
|---|---|---|
| `RunHeader` | harness | schema_version, app, backend, policy, topology, seed |
| `EntanglementRequested` | backend | req_id, src, dst, n, demand, t |
| `EntanglementDelivered` | backend | req_id, actual_fidelity, latency, pair_age, t |
| `ContractViolation` | backend | req_id, kind∈{fidelity,deadline,staleness,dropped}, t |
| `ClassicalMessage` | backend | src, dst, n_bytes, t |
| `Measurement` | app | node, basis, result, t |
| `AppOutcome` | app | role, success, utility, payload, t |

`utility` on `AppOutcome` is application-defined in `[0,1]` and is what the
staleness/fidelity curves are plotted against. `pair_age` on delivery is what
makes staleness-tolerance curves computable directly from a trace.

---

## 5. Metrics & reporting (`qnetbench.metrics`)

All computed from a trace (or a set of traces). Standard report:

- **Delivered fidelity-throughput** — pairs/sec weighted by delivered fidelity,
  and the raw (rate, mean-fidelity) pair.
- **Contract-violation rate** — per `kind`, per application.
- **Latency distribution** — request→delivery, p50/p95/p99.
- **Staleness-tolerance curve** — utility vs `pair_age`, per application.
- **Fidelity/rate indifference curve** — utility vs delivered fidelity at fixed
  rate and vice-versa (swept across runs).
- **Classical-coupling ratio** — classical bytes / entangled pair, and the
  request→classical dependency depth.

Report is emitted as machine-readable JSON *and* a rendered summary. Curves ship
as data (CSV/JSON) so the characterization paper's figures regenerate from source.

---

## 6. Demand-signature taxonomy (`qnetbench.characterize`)

The dimensions we measure per application (Deliverable 2):

1. **Burstiness** — inter-request-arrival distribution; Fano factor / index of
   dispersion; on/off duty cycle.
2. **Fidelity-vs-rate sensitivity** — shape of the utility indifference curves.
3. **Staleness tolerance** — utility decay vs pair age (feeds Issue #5).
4. **Classical-communication coupling** — coupling ratio + dependency structure
   (does each quantum op block on a classical round-trip?).
5. **Deadline-criticality** — hard vs soft; distribution of latency budgets.
6. **Multipartiteness** — bipartite vs GHZ/multipartite demand.

Each application gets a signature vector on these axes; the "characterization
paper" is the cross-application table + curves, regenerated from traces.

---

## 7. Application set (target 6–8, spanning the issue's classes)

| # | Application | Class | Signature emphasis |
|---|---|---|---|
| 1 | QKD (BB84/E91) | key distribution | steady, rate-hungry, fidelity-thresholded |
| 2 | Blind Quantum Computation | BQC | bursty, latency-coupled, high-fidelity, heavy classical coupling |
| 3 | Distributed gate (teleported CNOT) | distributed gates | deadline-critical, staleness-intolerant |
| 4 | CHSH / DIQKD test | key distribution (device-indep) | correlation-quality-sensitive |
| 5 | Clock synchronization | sensing | correlation-quality-sensitive, steady |
| 6 | Anonymous transmission | multipartite broadcast | GHZ demand, multipartite |
| 7 | *(stretch)* Leader election | coordination | multipartite, bursty |
| 8 | *(stretch)* Teleportation-based DQC circuit | distributed gates | mixed, deadline-driven |

Phase 0 builds #1–#3 (they span the three most distinct signatures and are enough
to demonstrate ranking inversion). #4–#6 complete the "credible suite" claim.

---

## 8. Arbitration seam & cross-policy evaluation (`qnetbench.policies`)

Arbitration is a **run-level toggle**, borrowing MQT Bench's model where the user
picks the *level* they want rather than being locked into ours:

- **`native`** — the backend uses its own default scheduling/routing (SeQUeNCe's
  reservation/RSVP layer, NetSquid's native behavior). This is the "standard
  implementation" that most papers run today, and it is the **opt-out**: people
  who just want to run the application as-is never touch our policy layer.
- **`policy:<name>`** — a **backend-agnostic arbiter inside qnetbench** intercepts
  entanglement requests and applies the chosen policy. To make policy behavior
  *identical across backends*, the arbiter sits **above** the backend's low-level
  pair-generation primitives and performs ordering/routing itself, rather than
  hooking each simulator's internal reservation layer. We rebuild the arbiter
  once, in qnetbench; every backend then exposes the same policy semantics.

```python
class Policy(Protocol):
    name: str
    def order(self, pending: list[EntanglementRequested],
              state: NetworkState) -> list[req_id]: ...
    def route(self, req: EntanglementRequested,
              topology: Topology) -> Path: ...

# Backends implement only the primitive seam the arbiter drives:
class PrimitiveBackend(Protocol):
    def generate_pair(self, src: NodeId, dst: NodeId,
                      demand: Demand) -> EntanglementHandle: ...
    def supports_native_arbitration(self) -> bool: ...   # for `native` mode
```

We implement 2–3 *published* policies (FIFO baseline, a fidelity-first /
threshold policy, a deadline/EDF-style policy) and run the full suite under each,
plus `native`. **Deliverable 4 is proven when the policy ranking inverts across
workload classes** — e.g. EDF wins on distributed-gate (deadline) traffic but
loses to fidelity-first on QKD. Every result in the report is tagged with the
backend and arbitration mode it came from, so `native`-vs-`policy` differences
are visible too.

---

## 9. Cross-backend equivalence testing

The thing that makes the suite trustworthy. For each application, a
backend-agnostic test asserts that *outcome invariants* hold on every backend:
QKD produces matched sifted keys with QBER below threshold; teleported-CNOT
reproduces the truth table; CHSH yields S ≈ 2√2 under a noiseless config. Physics
differs across simulators, so we assert *invariants and tolerances*, not
bit-identical traces. The reference backend is the oracle for these tests (it's
the only one that runs in CI without registration).

---

## 10. Repository layout

```
qnetbench/
  api/          # the shim: ABCs, Demand, Host, sockets, Qubit, gates
  trace/        # pydantic event models, JSONL reader/writer, schema_version
  apps/         # qkd.py, bqc.py, distributed_gate.py, ...  (import only api+trace)
  backends/
    reference/  # pure-Python, no external deps — CI oracle
    sequence/   # SeQUeNCe adapter
    netsquid/   # NetSquid adapter
  policies/     # fifo.py, fidelity_first.py, edf.py, base.py
  metrics/      # readers → metrics + curves + report
  characterize/ # demand-signature extraction
  harness/      # run matrix, cli.py
tests/
  invariants/   # per-app cross-backend equivalence
  golden/       # trace schema round-trip + versioning
docs/
  design.md     # this file
  specs/        # versioned trace-spec + metric-spec (machine-readable)
  adopting.md   # "add an application" / "add a backend" guides
traces/         # published reference traces (Deliverable 3)
```

Tooling: `pyproject.toml`, mypy-strict, ruff, pytest, GitHub Actions CI running
the reference backend + invariant tests. SeQUeNCe/NetSquid backends tested behind
optional extras (`pip install qnetbench[sequence]`, `[netsquid]`).

---

### SeQUeNCe backend model — RESOLVED: hybrid (entanglement-supply)

SeQUeNCe owns the entanglement-generation physics; qnetbench owns app execution.
For each edge we run a SeQUeNCe reservation and extract the delivered-pair stream
(inter-arrival timing + fidelity); the verified reference engine then *replays*
that supply and runs the local quantum ops + classical protocol. This targets the
layer Issue #4 discriminates on (how entanglement is supplied), reuses the
reference engine (so the SeQUeNCe backend is a ~90-line subclass overriding two
physics hooks), and keeps cross-backend equivalence clean (delivered fidelity is
the controlled variable). Two SeQUeNCe-specific notes: delivered fidelity is set
by the memory `raw_fidelity` param; and SeQUeNCe keeps process-global state that
misbehaves under the engine's worker threads, so every edge's supply is
pre-generated eagerly on the main thread in `SequenceBackend.__init__`.

## 11. Roadmap — phases mapped to the issue's deliverables

| Phase | Output | Issue deliverable |
|---|---|---|
| **0. Skeleton** ✅ | scaffolding, typed `api` + `trace`, reference backend, apps #1–#3, metrics, CLI, CI, invariant tests | foundation for all |
| **1. SeQUeNCe backend** ✅ | `backends/sequence` (hybrid) + cross-backend invariants for #1–#3 | Deliverable 1 (½) |
| **2. NetSquid backend** ✅ | `backends/netsquid` (hybrid) + shared `ReplayBackend` base + equivalence tests | Deliverable 1 (✔ ≥2 sims) |
| **3. Full app set** ✅ | apps #4–#6 (chsh, clock_sync, anonymous) across all backends; star topology + GHZ fusion | Deliverable 1 (✔ 6–8 apps) |
| **4. Characterization** ✅ | `qnetbench.characterize`: single-trace signatures + fidelity/staleness curves + cross-app table + CLI; pair-aging in the reference backend | Deliverable 2 |
| **5. Spec freeze** ✅ | versioned trace + metric JSON Schemas in `docs/specs` (drift-guarded) + published reference traces in `traces/` with a checksummed manifest; `qnetbench spec`/`corpus` | Deliverable 3 |
| **6. Cross-policy eval** ✅ | `qnetbench.contention`: multi-tenant DES, 3 policies × 2 workload mixes; EDF↔fidelity_first ranking inversion; `qnetbench contention` | Deliverable 4 |
| **7. Adoption docs** ✅ | `docs/adopting.md` (add-an-app / add-a-backend / consume-traces, examples verified to run); released to PyPI | Deliverable 5 (the real success metric) |

Each phase is independently reviewable and leaves the repo runnable.

## 13. Future benchmarks (planned)

The five deliverables are complete; these extend *coverage and realism*. An
application is one file against the API, so the suite has no cap on size — new apps
inherit cross-backend equivalence, a demand signature, and a published trace for
free.

- **DQC circuit-demand generator** ✅ — `qnetbench.circuits` (distributed-circuit IR,
  ASAP layering, GHZ/QFT/random mirror circuits, `from_qiskit` loader) + `apps/dqc.py`
  (executes a partitioned circuit; each non-local gate is a teleported gate whose
  deadline is its layer × a per-layer budget, so the trace is the circuit's
  Entanglement Demand Schedule). Registered as `dqc_ghz4`/`dqc_qft4`/`dqc_random4`;
  the shared teleported-gate primitive lives in `apps/telegate.py`. Optional MQT
  Bench / Qiskit circuits load behind the `mqt` extra.
- **Entanglement swapping** ✅ — `apps/swap.py` (`entanglement_swap`): a 3-node line
  alice—repeater—bob where the repeater does a Bell-state measurement to swap two
  elementary links into one end-to-end pair (bob applies the Pauli correction). Adds
  the multi-hop relay/routing demand class (two elementary pairs per end-to-end
  unit). *Still planned:* multi-hop QKD over a repeater chain (key from swapped pairs).
- **Core / catalog split** ✅ — the suite is now a curated **core** (`available_apps()`,
  ~11 distinct protocols, run in CI + corpus + cross-backend equivalence) plus a
  **catalog** (`catalog_apps()`, 50+) generated as DQC over circuit families
  (GHZ/QFT/random/graph/IQP/HEA) × sizes, resolvable on demand via `get_app` and
  `qnetbench run <name>` / `list --all`, but not baked into CI. The MQT Bench / SPEC
  model — coverage from the core, quantity from the generator.
- **Teleportation** ✅ — `apps/teleport.py` (`teleportation`): moves a *state* (not a
  gate) via one EPR pair + two classical bits; added to the core.
- **Multi-hop QKD** ✅ — `apps/multihop_qkd.py` (`multihop_qkd`): key distribution over
  a repeater chain (swap → end-to-end pair → BBM92 sifting, classical relayed through
  the repeater). Multi-hop *and* fidelity-thresholded — the only 3-party key app.
- **Shared randomness** ✅ — `apps/shared_randomness.py` (`shared_randomness`): the only
  app using `purpose="measure"` (the backend measures on delivery, no local qubit) —
  correlated shared random bits from Z-measured pairs.
- **Quantum secret sharing** ✅ — `apps/secret_sharing.py` (`secret_sharing`): a dealer
  splits a secret bit among two players over a GHZ; both together (neither alone)
  reconstruct it via the GHZ X-parity.
- **Conference key agreement** ✅ — `apps/conference_key.py` (`conference_key`): the
  N-party generalization of QKD — a hub fuses three pairs into a 4-party GHZ and all
  four measure Z for one shared key bit. The highest party count (4) and the most
  fidelity-demanding app in the suite (a 4-party GHZ from 3 pairs is fragile).
- **Verified BQC** ✅ — `apps/verified_bqc.py` (`verified_bqc`): BQC with interleaved
  trap rounds; an accept/reject verification (utility = trap pass rate, success =
  every trap passed) rather than a plain computation. Shares the UBQC gadget in
  `apps/ubqc.py`.
- **Leader election** ✅ — `apps/leader_election.py` (`leader_election`): fair leader
  election among five parties via shared 5-party GHZ randomness. The highest party
  count (5) and the most fidelity-demanding app in the suite (F½util 0.97).
- **Prepare-and-measure BB84** ✅ — `apps/bb84.py` (`bb84`): the original BB84, where
  Alice *sends the qubit itself* (random bit, random basis) and Bob measures. Added a
  single-qubit-transmission primitive to the api — `Host.qsend` / `Host.qrecv` (a
  blocking rendezvous so the register stays small) — and a `qubit_sent` trace event
  (schema/api bumped to 0.2.0). The only app in the single-qubit-transmission demand
  class (no shared pairs); the characterizer now counts `qubit_sent` as demand.
- **More protocol apps from the literature** *(planned)* — see [§14](#14-remaining-work-todo).

---

## 14. Remaining work (TODO)

Deliverables 1–5 are complete; the suite is **22 core protocols + a 61-entry
catalog** (42 generated DQC instances, 3 overlapping the core; unbounded via the DQC
generator) across **3 backends**. What follows is optional/incremental, roughly in
priority order.

### Usage & docs
- ✅ **Usage guide** — how to run, what data you get, topologies, definable vs.
  predefined, and the benchmark count: [usage.md](usage.md).
- **Characterization figures** — `scripts/plot_curves.py` (+ the `viz` extra) turns
  `qnetbench characterize --out` JSON into fidelity/staleness figures; commit a
  regenerated `figures/` set (or a make target) so the paper's plots track the code.

### Release
- **Publish a real PyPI release.** What's on PyPI is only the `v0.0.1` name
  reservation; the current suite (api/schema **0.2.0**, 22 protocols) is unreleased.
  Bump `pyproject` version → 0.2.0, `python -m build`, `twine upload` (needs the
  maintainer's token).

### Remaining algorithms
- ✅ **Byzantine agreement / detectable broadcast** (`byzantine_agreement`) — 3-party
  GHZ; an honest general reaches consensus, a faulty one's equivocation is detected.
- ✅ **B92 and six-state QKD** (`b92`, `six_state`) — prepare-and-measure variants over
  `qsend`/`qrecv`, with lower sifting yield / higher QBER tolerance than BB84.
- ✅ **((3,5)) threshold secret sharing** (`threshold_secret_sharing`) — the canonical
  Cleve–Gottesman–Lo scheme over the [[5,1,3]] five-qubit code: any 3 of 5 reconstruct,
  any 2 learn nothing. A GHZ can't do this, so it needs a distance-3 code with
  redundancy; the encoder + per-subset reconstruction table are synthesised and
  numerically verified against the code's stabilisers.
- Higher-N conference key / a general ((k,n)) generator remain open.

### Bugs / known limitations
*No functional bugs were found in audit — the suite is deterministic per seed, with
no deadlocks over 20 seeds × all apps, no broken catalog entries, and no register
leaks. These are constraints to be aware of:*
- **Statevector scaling** — the reference register is O(2ⁿ) in live qubits, so DQC and
  multipartite apps are practical to ~n ≤ 14 (the catalog caps DQC at n ≤ 10). *Fix:*
  a stabilizer / density-matrix backend for Clifford circuits.
- **`qsend`/`qrecv` single transfer in flight per edge** — fine for the 2-party
  lockstep apps; a pipelined single-qubit protocol would need a queued quantum channel.
- **BB84 on the simulator backends** uses the `LinkModel` transmission fidelity, not
  the simulator's channel (single-qubit transmission isn't in the hybrid supply model).
- **Prepare-and-measure metrics** — `delivered_rate` is pairs-only (0 for BB84); its
  demand shows up in `qubits_sent`. A qubit-transmission rate could be added.
- **Versioning** — a new event kind was treated as a minor bump (0.2.0), whereas the
  stability policy calls additive changes a patch. Harmless; clarify the policy.

### Coverage / infrastructure gaps
- **CI runs the reference backend only.** Cross-backend equivalence (SeQUeNCe/NetSquid)
  is exercised locally in the two venvs, not in GitHub CI. *Fix:* a CI job that
  `pip install`s SeQUeNCe to cover one simulator. (The full catalog *is* now in CI.)
- **The policy arbiter is a standalone contention sim** (`qnetbench.contention`), not
  wired into the live cooperative backend — single-tenant runs never contend.
- **General multi-hop routing / entanglement swapping in the backend** — apps do it at
  the protocol level over star topologies; the backend models direct links + fusion.
