# Adopting qnetbench

This suite has three extension points, each designed to be small:

1. [Add an application](#add-an-application) — one file against the portable API.
2. [Add a backend](#add-a-backend) — a ~1-method subclass.
3. [Consume traces](#consume-traces) — read JSONL in any language; no import needed.

You never touch the internals of the layers below you. Applications don't import
backends; backends don't import applications.

---

## Add an application

An application is any object satisfying the `Application` protocol: a `name`, a
`roles()` list, and a `run(host, role, cfg)` method that the harness calls once per
role (concurrently). Roles map to nodes by name; a 2-role app runs on a direct
link, a 3+-role app on a star with `roles()[0]` as the hub — both built for you.

Inside `run`, the `host` is the whole runtime surface (it never leaks a simulator):

| Call | Does |
|---|---|
| `host.epr_socket(peer).request(n, demand)` | request `n` entangled pairs under a `Demand` contract; returns handles |
| `host.classical_socket(peer).send(b)` / `.recv()` | classical messaging (bytes) |
| `host.qalloc()` | allocate a fresh local qubit |
| `host.rng` | a deterministic, per-node seeded numpy `Generator` — use it for all randomness |
| `host.record_measurement(basis, bit)` | annotate the trace with a measurement |
| `host.now()` / `host.sleep(dt)` | simulated time |

A qubit handle exposes `.qubit` (the local half; `None` if `purpose="measure"`),
`.fidelity`, `.pair_age`, `.violations`, and `.ok`. A `Qubit` supports
`apply(gate, *params)`, `cnot(target)`, `cz(target)`, and `measure(basis)`
(destructive — it frees the qubit). Gates and bases come from `qnetbench.api`.

The **`Demand`** attached to every request is the contract schedulers read and
metrics score against — set it honestly for your workload:

```python
Demand(min_fidelity=0.9, latency_budget=0.05, deadline=None,
       staleness_tolerance=None, priority=1.0, purpose="keep")
```

### A complete minimal application

```python
from qnetbench.api import AppOutcome, Basis, Demand, Host, Role

class Ping:
    """Two nodes share a pair, each measures in Z, and they check the correlation."""

    name = "ping"

    def roles(self) -> list[Role]:
        return ["alice", "bob"]

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        peer = "bob" if role == "alice" else "alice"
        handle = host.epr_socket(peer).request(1, Demand(min_fidelity=0.8))[0]
        assert handle.qubit is not None
        bit = handle.qubit.measure(Basis.Z)
        host.record_measurement(Basis.Z, bit)

        cls = host.classical_socket(peer)
        cls.send(bytes([bit]))      # send is non-blocking; recv blocks
        theirs = cls.recv()[0]

        agree = bit == theirs       # |Φ+> is perfectly Z-correlated when noiseless
        return AppOutcome(role=role, success=agree, utility=1.0 if agree else 0.0)
```

Register it in [`qnetbench/apps/__init__.py`](../qnetbench/apps/__init__.py) by
adding `Ping()` to the `_REGISTRY` tuple. Then it runs on every backend:

```bash
qnetbench run ping                  # reference
qnetbench run ping --backend sequence
```

### Guidance

- **Use `host.rng` for every random choice** (basis picks, inputs). Runs are
  reproducible per seed; `random`/`numpy.random` global state would break that.
- **Avoid deadlocks**: both sides should `send` (non-blocking) before they `recv`
  (blocking). A role that never completes raises a clear error, not a hang.
- **Utility is your app's quality in `[0,1]`** — make it move with fidelity (it's
  what the characterization curves are plotted against). If your app has a security
  or correctness threshold, collapse utility to 0 below it (see QKD).
- **Test it** by asserting an invariant on the reference backend at fidelity 1.0
  (see [`tests/test_app_invariants.py`](../tests/test_app_invariants.py)); the same
  assertion becomes your cross-backend equivalence test for free.

---

## Add a backend

Most backends are *supply* backends: an external simulator owns the
entanglement-generation physics, and qnetbench replays that supply through its
verified execution engine. You implement one method — `_make_supply(node, peer)` —
returning the delivered-pair stream for an edge:

```python
from qnetbench.api.types import NodeId
from qnetbench.backends.replay import ReplayBackend, Supply

class ConstantRateBackend(ReplayBackend):
    backend_name = "constant"

    def _make_supply(self, node: NodeId, peer: NodeId) -> Supply:
        link = self.topology.link(node, peer)
        n = 10_000
        return Supply(
            inter_arrivals=[1e-3] * n,                 # 1000 pairs/second
            fidelities=[link.link_fidelity] * n,       # constant delivered fidelity
            classical_latency=link.attempt_latency,    # one-way classical delay (s)
        )
```

`Supply` is just `(inter_arrivals, fidelities, classical_latency)` — the gaps
between deliveries, each pair's fidelity, and the classical delay. The base class
pre-generates one supply per edge (eagerly, on the main thread) and replays it; the
application, local quantum ops, and classical protocol are all handled for you.

Wire it into [`qnetbench/harness/runner.py`](../qnetbench/harness/runner.py) with a
name → class branch (guard the import if it needs an optional dependency, as the
`sequence`/`netsquid` backends do). See
[`qnetbench/backends/sequence/`](../qnetbench/backends/sequence/) and
[`netsquid/`](../qnetbench/backends/netsquid/) for real examples that drive a
simulator inside `_make_supply` and extract its delivered-pair stream.

A backend that models physics more deeply than a replayed supply can instead
subclass `ReferenceBackend` and override `_sample_pairs` and `_classical_latency`
directly.

### Equivalence

Once registered, your backend inherits the cross-backend equivalence suite: the
same application invariants (asserted as tolerances, since physics differs) must
hold on it. Add it to the skip-guarded test files alongside `sequence`/`netsquid`.

---

## Consume traces

A run is JSONL — one event per line — and the schema is the versioned contract in
[`docs/specs/`](specs/). You need nothing from qnetbench to read it:

```python
import json

pairs = fidelity_sum = 0.0
for line in open("traces/qkd.jsonl"):
    e = json.loads(line)
    if e["kind"] == "ent_delivered":
        pairs += 1
        fidelity_sum += e["actual_fidelity"]
print("delivered pairs:", pairs, "mean fidelity:", fidelity_sum / pairs)
```

Every event carries a simulated time `t` and a `kind` discriminator; the full event
list and the demand-contract layout are in [`docs/specs/README.md`](specs/README.md).
Published reference traces for all six applications, with a checksummed manifest,
live in [`traces/`](../traces/) — regenerate them with `qnetbench corpus`.
