# Applications

An application is a protocol written once against the [portable
API](../reference/api.md) — a `name`, a list of `roles()`, and a `run(host, role,
cfg)` method the harness calls once per role, concurrently. It never imports a
simulator, so it runs unchanged on every [backend](backends.md).

The suite follows the SPEC / MQT Bench model: a **curated core** of distinct
protocols for coverage, and a **generator** for quantity.

```bash
qnetbench list          # the 27 core protocols
qnetbench list --all    # the 66-entry catalog
qnetbench run <name>    # any entry from either
```

| Layer | Count | What it is |
|---|---|---|
| Core protocols | **27** | hand-written protocols spanning every demand class; CI, the reference corpus and the cross-backend equivalence suite all iterate these |
| Runnable catalog | **66** | the core plus 39 generated distributed-circuit instances |
| Generatable | unbounded | any circuit family × size × partition, or any Qiskit / MQT Bench circuit |

## The core

Chosen so that the demand classes — steady and rate-hungry, bursty and
latency-coupled, deadline-critical, multipartite, prepare-and-measure — are each
represented by a real protocol rather than a parameter setting.

### Key distribution

| App | Protocol | Demand signature |
|---|---|---|
| `qkd` | entanglement-based key distribution (E91/BBM92) | steady, rate-hungry, fidelity-thresholded |
| `bb84` | prepare-and-measure BB84 | single-qubit **transmission**, no shared pairs |
| `b92` | B92, two non-orthogonal states | transmission, lower sifting yield |
| `six_state` | six-state QKD, three bases | transmission, higher QBER tolerance, lowest yield |
| `multihop_qkd` | QKD over a repeater chain | multi-hop **and** steady; QBER compounds over both hops |
| `chsh` | device-independent QKD via a CHSH test | correlation-quality-sensitive |

### Computation

| App | Protocol | Demand signature |
|---|---|---|
| `bqc` | universal blind quantum computation | bursty, latency-coupled, classical-heavy, high fidelity |
| `verified_bqc` | trap-based verified BQC | BQC plus trap overhead; accept/reject verification |
| `distributed_gate` | teleported CNOT between nodes | deadline-critical, staleness-intolerant |
| `distilled_gate` | distil, then consume, a distributed gate | **mixed criticality** — the only app emitting both best-effort and deadline demand |
| `dqc_ghz4`, `dqc_qft4`, `dqc_random4` | distributed circuits | demand **derived from a real circuit**: bursty and deadline-critical, shaped by the circuit |

### Transport and supply

| App | Protocol | Demand signature |
|---|---|---|
| `teleportation` | state teleportation | steady, latency-coupled, high fidelity |
| `heralded_teleport` | teleportation over a probabilistic BSM | **on/off duty cycle** — the only super-Poissonian app (Fano 2.20), geometric retry bursts |
| `entanglement_swap` | swapping on a repeater line | multi-hop; two elementary pairs per end-to-end unit |
| `distillation` | BBPSSW/DEJMPS distillation | **produces** entanglement — rate-hungry, deliberately *low* `min_fidelity`, staleness-critical |
| `shared_randomness` | shared randomness from measured pairs | steady, rate-hungry, `purpose="measure"` |

### Multiparty and security

| App | Protocol | Demand signature |
|---|---|---|
| `anonymous_transmission` | multipartite broadcast (GHZ) | 3-party GHZ demand |
| `byzantine_agreement` | detectable broadcast / Byzantine agreement | 3-party GHZ, bursty, consensus |
| `secret_sharing` | (n,n) quantum secret sharing | multipartite, threshold reconstruction |
| `threshold_secret_sharing` | ((3,5)) threshold QSS, five-qubit code | 5-party transmission; any 3 reconstruct, any 2 learn nothing |
| `conference_key` | 4-party conference key agreement | 4-party GHZ, highly fidelity-demanding |
| `leader_election` | fair leader election | 5-party — the highest party count and the most fidelity-demanding app |
| `oblivious_transfer` | 1-out-of-2 quantum OT (BBCS) | transmission; the lowest classical coupling in the suite |
| `position_verification` | quantum position verification | deadline set by **physics** — a late pair is insecure, not slow |
| `clock_sync` | sensing via entanglement phase estimation | steady, correlation-quality-sensitive |

The measured signature for each of these is in [Characterization](characterization.md);
the demand classes are not claims, they are the output of `qnetbench characterize`.

## The generated catalog

The other 39 entries are `DQC` over the built-in circuit families at sizes 4–10:

```text
dqc_ghz4 … dqc_ghz10          dqc_qft4 … dqc_qft10
dqc_random4 … dqc_random10    dqc_graph4 … dqc_graph10
dqc_iqp4 … dqc_iqp10          dqc_hea4 … dqc_hea10
```

Six families × seven sizes = 42, of which three (`dqc_ghz4`, `dqc_qft4`,
`dqc_random4`) are also in the core, giving 66 catalog entries. Each is runnable by
name with no extra setup:

```bash
qnetbench run dqc_iqp8
qnetbench run dqc_hea10 --arbitration policy:edf
```

Beyond the catalog the generator is unbounded — see [Circuits](circuits.md) and the
[circuit-loading tutorial](../tutorials/distributed-circuits.md).

## Resolving applications in Python

```python
from qnetbench.apps import available_apps, catalog_apps, get_app, register_app

available_apps()          # the 27 core names
catalog_apps()            # all 66
app = get_app("bqc")      # the Application instance
app.name, app.roles()     # ('bqc', ['alice', 'bob'])
```

`register_app(app)` adds an instance you built at runtime to the catalog so that
`run_once`, `characterize_app` and the rest can resolve it by name.

## Roles and nodes

Roles are mapped onto nodes of the same name. The harness picks a default topology
from the role count — a direct link for two roles, a star with `roles()[0]` as the
hub for more — so a multipartite protocol fuses the hub's bipartite pairs into a
shared GHZ state. Override with `topology=`; see [Topologies and links](topologies.md).

## Adding your own

One file against the API, then one line in the registry. The complete worked
example — a `Ping` application that runs on every backend — is in
[Extending the suite](../adopting.md).
