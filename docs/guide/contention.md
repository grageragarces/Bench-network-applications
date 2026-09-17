# Contention

This is the result the suite exists to produce.

Running one application at a time, an arbiter almost never has to choose — there is
one pending demand and every policy agrees. Scheduling only matters under
**contention**: several tenants competing for a link whose entanglement supply is
below aggregate demand. `qnetbench contention` sets that up and shows that the best
policy **depends on what the workload is made of**.

```console
$ qnetbench contention
policy              deadline_heavy    fidelity_heavy
----------------------------------------------------
fifo                       0.800             0.867
fidelity_first             0.800             0.933*
edf                        0.817*            0.900
winner                         edf    fidelity_first

RANKING INVERSION — the best policy flips across workloads (deadline_heavy: edf  →  fidelity_heavy: fidelity_first).
Single-workload evaluation would have crowned one policy and been wrong on the other.
```

EDF wins on deadline-heavy traffic and is beaten on fidelity-heavy traffic;
`fidelity_first` does exactly the opposite. **A paper that evaluated on either
workload alone would have crowned one policy and been wrong about the other.** That
inversion is the argument that single-workload evaluation produces unreliable
rankings — and it is why a characterized benchmark suite is worth building.

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

Those two pressures pull in different directions. Which one a policy is good at
decides which mix it wins — hence the inversion.

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
print(has_inversion(exp))                           # True if the winner differs across mixes
print(winning_policies(exp["deadline_heavy"]))      # every policy tied at the top
```

Use `winning_policies` rather than `best_policy` wherever a tie would be reported
as a result: several operating points have two or three policies on exactly the
same score, and an argmax silently turns that into a winner.

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

The inversion requires the two workloads to place genuinely opposed demands on the
link; it is not a claim that any two mixes will disagree. What the experiment
supports is the narrower and more useful claim: **workload composition determines
which policy wins**, so a study that evaluates on one workload has not established
a ranking.

## API

[`Tenant`, `ContentionResult`, `app_profile`, `simulate`, `ranking_experiment`,
`default_mixes`, `burstiness_mixes`, `default_experiment`, `render_experiment`,
`best_policy`, `winning_policies`, `has_inversion`](../reference/contention.md).
