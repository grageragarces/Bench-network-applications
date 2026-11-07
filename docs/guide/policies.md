# Arbitration and policies

When several requests for entanglement contend for one link, something has to decide
the order. In qnetbench that is a `Policy`, and today policies take effect in one place:
the [contention model](contention.md), where several tenants share a link.

!!! warning "Policies do not change a single-application run"

    `qnetbench run bqc --arbitration policy:edf` is accepted and recorded in the trace
    header, but nothing consults the policy. A single application never has more than
    one pending request per link, so there is no order to decide, and the trace is the
    same as with `native` apart from that label.

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

Anything with a `name` and an `order` method satisfies the protocol, with no base
class:

```python
from qnetbench.policies import PendingRequest

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

To compare it with the built-ins, register it and name it in the contention experiment:

```python
from qnetbench.contention import default_mixes, ranking_experiment, render_experiment
from qnetbench.policies import register_policy

register_policy(PriorityWeighted())
print(render_experiment(ranking_experiment(
    default_mixes(100, seed=0),
    policies=("fifo", "edf", "priority"),
    capacity=160.0, link_fidelity=0.99, coherence_time=0.25,
)))
```

## Schedulers that keep state

A policy that needs history, such as the time since a tenant was last served, can define two
optional methods. `reset()` runs before each concurrent run, because a registered policy object is
shared between runs. `on_delivery(request, fidelity, at)` runs for each pair the link hands over,
with the time it arrives. `request.tenant` says who it was for.

```python
class LongestUnserved:
    name = "longest_unserved"

    def reset(self):
        self.last = {}

    def on_delivery(self, request, fidelity, at):
        self.last[request.tenant] = at

    def order(self, pending, now):
        def age(p):
            return now - self.last.get(p.tenant, 0.0)

        ranked = sorted(pending, key=lambda p: (-age(p), p.request_time, p.req_id))
        return [p.req_id for p in ranked]
```

These hooks run under `qnetbench.tenancy`, not in `contention.simulate`. A policy on one link can
order requests. It can't choose a path, because the suite has no routing.

## API

[`Policy`, `PendingRequest`, `Fifo`, `FidelityFirst`, `Edf`, `register_policy`](../reference/policies.md).
