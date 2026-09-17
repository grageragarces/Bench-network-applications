# Running benchmarks

Every run in the suite — the CLI, the tests, the characterizer, the contention
experiment — goes through one function.

```python
from qnetbench.harness import run_once

events = run_once("qkd", seed=0)
```

`run_once` executes one application, on one backend, under one arbitration mode,
over one topology, and returns the run's trace as a list of
[events](traces.md). Nothing is computed inline: metrics, signatures and figures
are all derived from that list afterwards.

## Signature

```python
run_once(
    app_name: str,
    *,
    seed: int = 0,
    backend: str = "reference",
    arbitration: str = "native",
    topology: Topology | None = None,
    cfg: dict[str, object] | None = None,
    pair_age: float = 0.0,
    coherence_time: float = math.inf,
) -> list[Event]
```

| Argument | Meaning |
|---|---|
| `app_name` | any name from `qnetbench list --all`, or one you [registered](#running-a-benchmark-you-built-yourself) |
| `seed` | seeds every RNG in the run — link sampling, measurement, and each node's application RNG, from independent streams |
| `backend` | `"reference"`, `"sequence"`, `"netsquid"` — see [Backends](backends.md) |
| `arbitration` | `"native"` or `"policy:<name>"` — see [Arbitration and policies](policies.md) |
| `topology` | a [`Topology`](topologies.md); defaults to a direct link for a 2-role app, a star for a multipartite one |
| `cfg` | per-run application configuration (below) |
| `pair_age` | deliver every pair already this many seconds old (reference backend only) |
| `coherence_time` | decoherence time constant used to age those pairs (reference backend only) |

The four arguments the CLI does not expose are `topology`, `cfg`, `pair_age` and
`coherence_time`. Reach for Python when you need them.

## Configuring an application

`cfg` is a loose `dict` read by the application itself, so the accepted keys depend
on which one you are running. Unknown keys are ignored, and a value of the wrong
type falls back to the default rather than raising:

```python
run_once("qkd", cfg={"rounds": 1024})
run_once("bqc", cfg={"depth": 8})
run_once("distributed_gate", cfg={"reps": 50})
```

| Application(s) | Keys |
|---|---|
| `qkd`, `bb84`, `b92`, `six_state`, `multihop_qkd`, `chsh`, `teleportation`, `entanglement_swap`, `shared_randomness`, `anonymous_transmission`, `byzantine_agreement`, `secret_sharing`, `threshold_secret_sharing`, `conference_key`, `verified_bqc` | `rounds` |
| `bqc` | `depth` |
| `distributed_gate`, `distilled_gate` | `reps` |
| `distillation` | `rounds`, `control_rounds` |
| `clock_sync` | `rounds`, `offset` |
| `heralded_teleport` | `sessions`, `mean_idle` |
| `leader_election` | `elections` |
| `oblivious_transfer` | `transfers`, `qubits` |
| `position_verification` | `rounds`, `response_budget` |
| `dqc_*` | none — a DQC benchmark is configured by its circuit, at construction |

Raising `rounds` mostly raises the sample size (and the run time); it does not
change the demand *shape*, which is what the [characterization](characterization.md)
measures.

## Determinism

A run is fully determined by `(app, seed, backend, topology, cfg)` and reproduces
byte for byte. That holds because:

- each node gets its own seeded `numpy.random.Generator`, exposed as `host.rng`,
  and applications are required to use it for every random choice;
- link sampling and quantum measurement draw from **separate** streams, so a
  backend that replays a pre-generated supply (and therefore draws no link samples)
  still produces the same measurement outcomes as the reference backend at the same
  seed. That is what makes cross-backend equivalence testable at all.

To vary a run, vary the seed:

```python
utilities = [compute_report(run_once("qkd", seed=s)).app_utility for s in range(32)]
```

## Modelling staleness

`pair_age` and `coherence_time` deliver pairs that were generated earlier and have
been sitting in memory decohering — the difference between a network that makes
entanglement on demand and one that serves it from a pre-made store:

```python
run_once("distributed_gate", pair_age=2e-3, coherence_time=1e-3)
```

Delivered fidelity decays from the link's fidelity toward the maximally mixed state
with time constant `coherence_time`. This is what the staleness-tolerance curve
sweeps, and it is only modelled on the reference backend — asking for it on
`sequence` or `netsquid` raises `NotImplementedError` rather than silently ignoring
it.

## Running a benchmark you built yourself

`run_once` resolves applications by name, so an instance you construct at runtime
needs to be registered first:

```python
from qnetbench.apps import register_app
from qnetbench.apps.dqc import DQC
from qnetbench.circuits import qft
from qnetbench.harness import run_once

name = register_app(DQC(qft(6), min_fidelity=0.95))   # -> "dqc_qft6"
events = run_once(name, seed=0, arbitration="policy:edf")
```

The registration lives in the importing process only, which is enough for
`run_once`, `characterize_app`, and everything else that takes a name. To expose
one on the command line, add it to `_CORE` in `qnetbench/apps/__init__.py`. The
full workflow is in
[Load any distributed circuit](../tutorials/distributed-circuits.md).

## From trace to numbers

```python
from qnetbench.harness import run_once
from qnetbench.metrics import compute_report, render
from qnetbench.trace import write_trace

events = run_once("qkd", seed=0)
write_trace("qkd.jsonl", events)          # the durable artifact
report = compute_report(events)           # metrics, computed from the trace
print(render(report))
```

Keep the trace, not the report: the report is a pure function of the trace, and a
trace outlives any particular set of metrics. See [Traces](traces.md).

## Errors you may hit

| Error | Cause |
|---|---|
| `KeyError: unknown app ...` | name not in the catalog; try `qnetbench list --all` |
| `ValueError: topology ... is missing nodes for roles [...]` | your topology has no node named after one of the app's roles |
| `ValueError: arbitration must be 'native' or 'policy:<name>'` | malformed `arbitration` string |
| `NotImplementedError: pair aging ... only modelled on the reference backend` | `pair_age`/`coherence_time` with `sequence`/`netsquid` |
| `RuntimeError: the 'sequence' backend needs ...` | the optional extra is not installed; the message carries the install command |
