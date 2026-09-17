# Quickstart

Five minutes, no simulator required — everything here runs on the pure-Python
`reference` backend.

## 1. Run a benchmark

```console
$ qnetbench run qkd
app=qkd  backend=reference  arbitration=native  seed=0
  app_success=True  app_utility=0.223
  pairs: requested=256 delivered=256 rate=997.3/s  mean_fidelity=0.950
  fidelity_throughput=947.8/s  violations: none  violation_rate=0.000
  latency(s): mean=0.0010 p50=0.0008 p95=0.0031 p99=0.0040
  classical: msgs=4 bytes=628 bytes/pair=2.5 msgs/pair=0.02
```

`app_utility` is the application's own quality measure in `[0, 1]` — for QKD it is
the secure-key fraction (sifted bits not spent on the public QBER test), so 0.223
is the protocol working, not failing. Every field is explained in
[Metrics and reports](guide/metrics.md).

## 2. See what is available

```console
$ qnetbench list
apps [core]: anonymous_transmission, b92, bb84, bqc, byzantine_agreement, chsh,
clock_sync, conference_key, distillation, distilled_gate, distributed_gate,
dqc_ghz4, dqc_qft4, dqc_random4, entanglement_swap, heralded_teleport,
leader_election, multihop_qkd, oblivious_transfer, position_verification, qkd,
secret_sharing, shared_randomness, six_state, teleportation,
threshold_secret_sharing, verified_bqc
policies:     edf, fidelity_first, fifo
```

`qnetbench list --all` adds the generated distributed-circuit instances, for 66
runnable benchmarks. See [Applications](guide/applications.md).

## 3. Change what you are measuring

```bash
qnetbench run bqc --arbitration policy:edf     # schedule under a chosen policy
qnetbench run dqc_qft8                         # any catalog entry
qnetbench run qkd --backend sequence           # supply entanglement from SeQUeNCe
qnetbench run qkd --seed 3                     # a different (deterministic) run
qnetbench run qkd --json                       # machine-readable report
qnetbench run qkd --out run.jsonl              # also write the trace
```

## 4. Do it from Python

```python
from qnetbench.harness import run_once
from qnetbench.metrics import compute_report, render

events = run_once("distributed_gate", seed=0)   # a list of trace events
report = compute_report(events)                 # metrics computed from the trace
print(render(report))

print(report.app_utility, report.violation_rate, report.latency_p95)
```

Every run is deterministic in its seed, so `(app, seed, backend, topology)`
reproduces byte for byte.

## 5. Change the physics

The link model is yours to set — fidelity, delivery latency, and the spread on
delivered fidelity:

```python
from qnetbench.harness import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, line2

noisy = line2("alice", "bob", link=LinkModel(link_fidelity=0.80, attempt_latency=5e-3))
print(compute_report(run_once("qkd", topology=noisy)).app_utility)
```

See [Topologies and links](guide/topologies.md).

## 6. Measure a workload instead of a run

A single run tells you how one application did. The *characterization* tells you
what kind of demand it places on a network — which is what makes workloads
comparable:

```bash
qnetbench characterize qkd          # one application
qnetbench characterize --out sig/   # all 27, plus per-app curve JSON
```

See [Characterization](guide/characterization.md).

## 7. Show that the policy ranking inverts

```bash
qnetbench contention
```

This is the suite's headline result — the best scheduling policy depends on the
workload mix. See [Contention](guide/contention.md).

## Next

- Run your own circuits: [Load any distributed circuit](tutorials/distributed-circuits.md)
- Consume the output elsewhere: [Traces](guide/traces.md)
- Add a protocol or a simulator: [Extending the suite](adopting.md)
