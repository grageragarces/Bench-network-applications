# Contention

A single application has nothing to arbitrate, since it never has more than one
pending request per link. Scheduling only matters under **contention**: several tenants
competing for a link whose entanglement supply is below aggregate demand.
`qnetbench contention` models that, and shows that which policy comes out best
**depends on the workload, the declared contracts and the metric**.

This is a queueing model. Tenants are demand streams read from application traces, not
running applications, and no backend is involved.

```console
$ qnetbench contention
32 independent arrival draws, 100 requests per tenant, 160 pairs/s,
link fidelity 0.99, coherence time 0.25 s

contract satisfaction, mean ± std across draws (* = highest mean)
policy               deadline_heavy     fidelity_heavy
------------------------------------------------------
fifo                 0.507 ± 0.107      0.589 ± 0.044
fidelity_first       0.507 ± 0.107      0.683 ± 0.060*
edf                  0.809 ± 0.012*     0.550 ± 0.098
separation                17.4 s.e.          10.3 s.e.

worst-served application, mean satisfaction
policy               deadline_heavy     fidelity_heavy
------------------------------------------------------
fifo                          0.449              0.208
fidelity_first                0.449              0.212
edf                           0.045              0.127

The mixes share no best policy in 32 of 32 draws.
```

Read the two tables together:

- **The workload matters.** On aggregate satisfaction EDF leads one mix and is last on
  the other, and `fidelity_first` does the opposite. A study using one mix alone would
  report one winner.
- **The metric matters.** All four `distributed_gate` tenants declare the same budget,
  so EDF amounts to serving tenants with deadlines before those without. Its 0.809 is
  `distributed_gate` at 1.000 and `qkd` at 0.045, so on the worst-served application it
  comes last on both mixes.
- **The contracts matter.** Lowering every `min_fidelity` by 0.05 or halving the deadline
  budgets removes the disagreement between the mixes.

## How the experiment works

Tenants are **parameterized by real applications**, not by invented parameters.
`app_profile` runs the application, reads its actual demand contract out of the
trace, and measures its actual inter-arrival pattern:

```python
from qnetbench.contention import app_profile

tenant = app_profile("distributed_gate", n_requests=12, interval=0.03)
tenant.min_fidelity, tenant.budget, tenant.pattern[:3]
```

The arrival pattern is normalised to mean 1.0 before being replayed at `interval`.
That removes the application's absolute rate — a property of the backend's link
model, not of the workload — while preserving the *shape* of its demand process.
Two mixes built this way can differ in burstiness at identical aggregate load,
which is what makes burstiness separately testable.

The simulation itself is a shared link producing one pair per service tick. At each
tick the policy ranks the pending queue and one request is served. A served
request's delivered fidelity **decays with how long it waited**, because the memory
holding its pair decoheres. So:

- a high-`min_fidelity` demand must be served *promptly* or it fails its contract;
- a deadline demand must be served *before its deadline* or it expires unserved.

Those two pressures pull in different directions, and which one a policy is good at
affects which mix it wins.

## The two mixes

| Mix | Tenants |
|---|---|
| `deadline_heavy` | 4 × `distributed_gate` + 1 × `qkd` |
| `fidelity_heavy` | 2 × `bqc` + 2 × `chsh` + 1 × `qkd` |

At the default operating point: capacity 160 pairs/s against five tenants at one
request per 30 ms (167 req/s of aggregate demand) — moderate overload — with link
fidelity 0.99 and coherence time 0.25 s.

!!! note "Give tenants their own arrivals"

    `default_mixes(seed=None)` keeps the synchronised model: every tenant of an
    application replays the same measured arrival sequence starting at `t=0`, so
    four `distributed_gate` tenants are really one stream counted four times. Pass
    an integer seed to give each tenant its own arrival realisation and start
    phase — which is what "five tenants" ought to mean, and which turns a single
    deterministic realisation into a distribution over arrival patterns.

## Driving it yourself

```python
from qnetbench.contention import (
    app_profile, default_mixes, ranking_experiment, render_experiment,
    has_inversion, winning_policies,
)

mixes = default_mixes(seed=7)                       # independent arrivals per tenant
exp = ranking_experiment(mixes, capacity=160.0, link_fidelity=0.99, coherence_time=0.25)
print(render_experiment(exp))
print(has_inversion(exp))                           # True if no policy is best on every mix
print(winning_policies(exp["deadline_heavy"]))      # every policy tied at the top
```

A winner is a set, because several operating points have two or three policies on
exactly the same score, and an argmax would silently turn that into a winner.

### Your own mix

```python
mix = {
    "my_workload": (
        [app_profile("bqc", 100, 0.03, trace_seed=s) for s in range(3)]
        + [app_profile("distillation", 100, 0.03, trace_seed=s) for s in range(2)]
    ),
}
print(render_experiment(ranking_experiment(
    mix, capacity=160.0, link_fidelity=0.99, coherence_time=0.25)))
```

### Isolating burstiness

`burstiness_mixes` builds two mixes that differ in **nothing but arrival shape** —
same application, same contracts, same tenant count, same mean rate; one replays
each tenant's measured inter-arrival pattern, the other issues on a perfectly
regular cadence:

```python
from qnetbench.contention import burstiness_mixes, ranking_experiment, render_experiment

exp = ranking_experiment(
    burstiness_mixes("heralded_teleport", count=5, seed=1),
    capacity=160.0, link_fidelity=0.99, coherence_time=0.25,
)
print(render_experiment(exp))
```

This isolates the burstiness axis of the characterization, which a fixed-cadence
arrival model simply cannot express — under it every tenant is smooth, regardless
of how the application actually behaves.

## Honest scope

Disagreement requires the two workloads to place opposed demands on the link, and it is
not a claim that any two mixes will disagree. The contract values behind these mixes are
also set by hand rather than derived from measurement. What the experiment supports is
narrower: **a ranking holds for a workload, a set of contracts and a metric**, so a study
that fixes all three has not established a general ranking.

## API

[`Tenant`, `ContentionResult`, `app_profile`, `simulate`, `ranking_experiment`,
`default_mixes`, `burstiness_mixes`, `replicated_experiment`, `render_replicated`,
`render_experiment`, `winning_policies`, `has_inversion`](../reference/contention.md).
