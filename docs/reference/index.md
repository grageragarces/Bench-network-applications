# API reference

Generated from the package's own docstrings by
[mkdocstrings](https://mkdocstrings.github.io/), so it cannot drift from the code.

## The frozen contracts

Two modules are contracts rather than implementation. Applications and third-party
tools depend on them, and they are versioned independently of the rest of the suite.

| Module | Version | What it is |
|---|---|---|
| [`qnetbench.api`](api.md) | `API_VERSION = 0.2.0` | the portable shim an application programs against — `Host`, `Qubit`, sockets, `Demand` |
| [`qnetbench.trace`](trace.md) | `SCHEMA_VERSION = 0.2.0` | the JSONL event schema and its I/O |

## Everything else

| Module | What it is |
|---|---|
| [`qnetbench.apps`](apps.md) | the benchmark applications and the registry |
| [`qnetbench.circuits`](circuits.md) | the distributed-circuit IR, the families, the Qiskit loader |
| [`qnetbench.harness`](harness.md) | `run_once` and the CLI |
| [`qnetbench.backends`](backends.md) | the reference engine and the replay seam |
| [`qnetbench.topology`](topology.md) | nodes, edges, and the link model |
| [`qnetbench.policies`](policies.md) | the arbitration seam and its baseline policies |
| [`qnetbench.metrics`](metrics.md) | traces to the standard report |
| [`qnetbench.characterize`](characterize.md) | demand-signature extraction and the curves |
| [`qnetbench.contention`](contention.md) | the multi-tenant cross-policy experiment |
| [`qnetbench.spec`](spec.md) | JSON Schema generation and the reference corpus |

## The shape of a dependency

Layers only ever point downwards, and the two arrows that are *absent* are the
important ones — applications never import backends, and backends never import
applications:

```text
  apps ──▶ api ◀── backends ──▶ topology
    │       ▲          │
    └──▶ harness ◀─────┘
             │
             ▼
           trace ──▶ metrics ──▶ characterize ──▶ contention
```
