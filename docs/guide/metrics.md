# Metrics and reports

Metrics are computed **from a trace**, never inline during a run. `compute_report`
is just the first consumer of the JSONL; a third-party tool reproduces the same
numbers from the same file without importing qnetbench.

```python
from qnetbench.harness import run_once
from qnetbench.metrics import compute_report, render

report = compute_report(run_once("qkd", seed=0))
print(render(report))
print(report.app_utility, report.latency_p95)
```

```console
app=qkd  backend=reference  arbitration=native  seed=0
  app_success=True  app_utility=0.223
  pairs: requested=256 delivered=256 rate=997.3/s  mean_fidelity=0.950
  fidelity_throughput=947.8/s  violations: none  violation_rate=0.000
  latency(s): mean=0.0010 p50=0.0008 p95=0.0031 p99=0.0040
  classical: msgs=4 bytes=628 bytes/pair=2.5 msgs/pair=0.02
```

`qnetbench run <app> --json` prints the same `Report` as JSON, and its JSON Schema
is the versioned [metric spec](../specs/README.md).

## What is in a report

### Provenance

| Field | Meaning |
|---|---|
| `app`, `backend`, `arbitration`, `topology`, `seed` | read straight from the trace's `run_header` |
| `sim_duration` | span of simulated time covered by the trace, seconds |

Because these come from the trace rather than from the call, a report always
describes the run that actually happened.

### Entanglement supply

| Field | Meaning |
|---|---|
| `n_requests` | `ent_requested` events — demand |
| `n_delivered` | `ent_delivered` events — supply |
| `qubits_sent` | single-qubit transmissions, for prepare-and-measure protocols |
| `delivered_rate` | delivered pairs per simulated second |
| `mean_fidelity` | mean delivered fidelity (transmission fidelity counts too) |
| `fidelity_throughput` | fidelity-weighted pairs per second — the honest rate figure |

`fidelity_throughput` exists because rate alone is gameable: a link that delivers
twice as many pairs at fidelity 0.5 is not twice as useful, and for most protocols
it is not useful at all.

### Contracts

| Field | Meaning |
|---|---|
| `violations` | count per kind: `fidelity`, `deadline`, `staleness`, `dropped` |
| `violation_rate` | total violations / delivered pairs |

A violation does not abort the run. The delivery still happens and the handle is
still returned, so the application decides how to degrade — which is the behaviour
a real deployment has, and it is what makes `app_utility` meaningful under stress.
`dropped` is reserved in the schema for a backend that refuses to serve a request
at all; none of the shipped backends emit it today.

### Latency

`latency_mean`, `latency_p50`, `latency_p95`, `latency_p99` — request to delivery,
in seconds. Tails matter more than means for deadline-critical workloads, which is
why the percentiles are reported by default.

### Classical coupling

| Field | Meaning |
|---|---|
| `classical_msgs`, `classical_bytes` | totals |
| `msgs_per_pair`, `bytes_per_pair` | per delivered pair |

This is one of the demand-signature axes: BQC and distributed gates sit around 2
messages per pair, QKD around 0.02. A network design that ignores the classical
channel is fine for one of those and badly wrong for the other.

### Application outcome

| Field | Meaning |
|---|---|
| `roles` | per-role `success` and `utility` |
| `app_success` | all roles succeeded |
| `app_utility` | mean utility across roles, in `[0, 1]` |

**`utility` is application-defined quality, not a score out of one.** QKD's utility
is its secure-key fraction — the sifted bits left after half of them are spent on
the public QBER test — so `app_utility=0.223` is the protocol working correctly,
not a failure. It collapses to 0 above the QBER threshold, which is what makes QKD
fidelity-thresholded. What matters is how utility *moves* with
fidelity and staleness — which is exactly what
[characterization](characterization.md) measures.

## The demand contract

Every entanglement request carries a `Demand`, recorded in the trace and read by
schedulers:

```python
from qnetbench.api import Demand

Demand(
    min_fidelity=0.9,           # below this, a delivery violates the contract
    latency_budget=0.05,        # soft deadline, measured from the request
    deadline=None,              # hard absolute deadline (distributed gates)
    staleness_tolerance=1e-3,   # maximum usable age of a pre-made pair
    priority=1.0,
    purpose="keep",             # or "measure": measured on delivery, no live qubit
)
```

This is what makes the suite discriminative rather than merely runnable: metrics
score requested against delivered, schedulers order by contract, and the
characterizer mines the contract distribution across a run.

## Computing your own

The report is a pure function of the event list, so you can compute anything else
the same way:

```python
from qnetbench.trace import read_trace
from qnetbench.trace.events import EntanglementDelivered

late = [e for e in read_trace("run.jsonl")
        if isinstance(e, EntanglementDelivered) and e.latency > 2e-3]
```

Or without importing qnetbench at all — see [Traces](traces.md).

## API

[`Report`, `RoleResult`, `compute_report`, `render`](../reference/metrics.md).
