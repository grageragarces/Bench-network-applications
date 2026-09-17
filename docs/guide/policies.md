# Arbitration and policies

When several requests for entanglement contend for one link, something has to
decide the order. In qnetbench that decision is a **run-level choice**, borrowing
MQT Bench's "pick your level" model:

| Mode | What happens |
|---|---|
| `native` | the backend's own default scheduling — FIFO on the reference backend, the simulator's own layer on SeQUeNCe / NetSquid |
| `policy:<name>` | a backend-agnostic arbiter applies the named policy identically on every backend |

```bash
qnetbench run bqc                              # native
qnetbench run bqc --arbitration policy:edf
qnetbench run bqc --arbitration policy:fidelity_first
```

`native` is the honest opt-out: it is what most papers actually run today, and
keeping it available means a comparison against the published baseline is always
one flag away.

## The built-in policies

```python
from qnetbench.policies import available_policies
available_policies()    # ['edf', 'fidelity_first', 'fifo']
```

| Policy | Orders by | Favours | At the expense of |
|---|---|---|---|
| `fifo` | request time | nothing in particular; the common default | everything equally |
| `fidelity_first` | highest `min_fidelity` first | fidelity-thresholded workloads (QKD, CHSH) | deadline-critical ones |
| `edf` | earliest effective deadline first | deadline-critical workloads (distributed gates) | steady rate-hungry ones |

They are intentionally simple and well established. The contribution of this suite
is the evaluation substrate, not a new scheduler — and a baseline that is
recognisable is worth more here than a clever one.

A request's **effective deadline** is its absolute `deadline` if it has one,
otherwise `request_time + latency_budget`, otherwise `+inf`. That is what lets EDF
order a queue mixing hard deadlines, soft budgets, and best-effort demand.

## The seam

A policy sees pending requests and returns them in service order:

```python
from qnetbench.policies import PendingRequest

class Policy(Protocol):
    name: str
    def order(self, pending: list[PendingRequest], now: SimTime) -> list[int]:
        """Return the req_ids of `pending`, most-urgent first."""
```

Each `PendingRequest` carries `req_id`, `src`, `dst`, `n`, the
[`Demand`](metrics.md#the-demand-contract) contract, and `request_time`, plus the
`effective_deadline()` helper. The contract is the only thing a policy gets to
reason about — which is deliberate, and is why `Demand` is declarative.

## Writing your own

Anything with a `name` and an `order` method satisfies the protocol; no base class,
no registration needed to use it from Python:

```python
from qnetbench.harness.runner import run_once
from qnetbench.policies.base import PendingRequest

class PriorityWeighted:
    """Serve the highest-priority demand first, breaking ties by arrival."""

    name = "priority"

    def order(self, pending: list[PendingRequest], now: float) -> list[int]:
        key = lambda p: (-p.demand.priority, p.request_time, p.req_id)
        return [p.req_id for p in sorted(pending, key=key)]
```

Always break ties deterministically (`request_time`, then `req_id`, as all three
built-ins do) — a policy that orders non-deterministically breaks the suite's
reproducibility guarantee.

To make it available by name — to `run_once(arbitration="policy:priority")`, the
CLI, and the contention experiment — add it to the registry in
`qnetbench/policies/builtin.py`.

## Where policies actually matter

Running one application at a time, the arbiter almost never has to choose: there is
usually a single pending demand, and every policy produces the same order. Policy
choice only shows up under **contention** — several tenants competing for a link
whose supply is below aggregate demand.

That is what [`qnetbench contention`](contention.md) sets up, and it is where the
suite's headline result lives: the ranking of these three policies *inverts*
between a deadline-heavy and a fidelity-heavy workload mix.

## API

[`Policy`, `PendingRequest`, `Fifo`, `FidelityFirst`, `Edf`](../reference/policies.md).
