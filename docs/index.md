# qnetbench

A benchmark suite and workload-characterization framework for **quantum-network
applications** — the SPEC/TPC/YCSB equivalent for the quantum internet.

Every scheduler, router and API paper in this field is evaluated on a workload its
own authors built, almost always QKD plus one bespoke toy, so no two results are
comparable. qnetbench fixes the substrate rather than the schedulers: a curated set
of protocols written once against a portable API, run unchanged on three simulator
backends, emitting a versioned trace that any third-party tool can consume.

```bash
pip install qnetbench
qnetbench run qkd
```

## What is in the box

| Layer | What you get |
|---|---|
| **27 core protocols** | QKD variants, BQC, distributed gates, distillation, GHZ multipartite protocols, repeater chains, DQC — one per distinct demand class |
| **66-entry catalog** | the core plus generated distributed-circuit instances; unbounded via the circuit generator |
| **3 backends** | `reference` (pure Python, always available), `sequence` (SeQUeNCe), `netsquid` (NetSquid) |
| **4 arbitration modes** | the backend's `native` scheduling, or `fifo` / `fidelity_first` / `edf` applied identically everywhere |
| **Characterization** | a measured demand signature per application: burstiness, classical coupling, deadline-criticality, fidelity and staleness curves |
| **A versioned trace** | JSONL with a JSON Schema, plus a checksummed reference corpus |

That is `66 × 3 × 4 = 792` predefined runnable configurations before the circuit
generator, which is unbounded.

## The result the suite exists for

Run several tenants against one oversubscribed link and the best scheduling policy
**flips** depending on what the workload is made of:

```console
$ qnetbench contention
policy              deadline_heavy    fidelity_heavy
----------------------------------------------------
fifo                       0.800             0.867
fidelity_first             0.800             0.933*
edf                        0.817*            0.900
winner                         edf    fidelity_first
```

EDF wins on deadline-heavy traffic and loses on fidelity-heavy traffic;
`fidelity_first` does the opposite. A paper that evaluated on either workload alone
would have crowned one policy and been wrong about the other. See
[Contention](guide/contention.md).

## Where to go next

<div class="grid cards" markdown>

- **New here** — [Install](install.md), then the [Quickstart](quickstart.md).
- **Running experiments** — the [command line](guide/cli.md) and
  [`run_once`](guide/running.md).
- **Understanding the output** — [metrics](guide/metrics.md) and
  [traces](guide/traces.md).
- **Your own circuits** — [Load any distributed circuit](tutorials/distributed-circuits.md).
- **Extending the suite** — [add an application or a backend](adopting.md).
- **Every symbol** — the [API reference](reference/index.md), generated from the
  source docstrings.

</div>

## Design commitments

These are load-bearing, and everything else follows from them:

1. **An application never imports a simulator.** It talks to the portable API shim
   in [`qnetbench.api`](reference/api.md) only. If the shim leaks simulator
   concepts, comparability dies.
2. **Demand is declarative.** Every request for entanglement carries a
   [`Demand`](reference/api.md#qnetbench.api.types.Demand) contract — minimum
   fidelity, latency budget, deadline, staleness tolerance, priority. Schedulers
   read contracts; metrics score violations of them.
3. **Everything observable is a trace.** Metrics are computed *from* the JSONL,
   never inline, so a third party reproduces our numbers without importing our
   code.
4. **Two independent backends or it does not count.** Cross-backend equivalence is
   a tested deliverable, not an aspiration.
5. **Runs are deterministic in their seed.** `(app, seed, backend, topology)`
   reproduces byte for byte.
