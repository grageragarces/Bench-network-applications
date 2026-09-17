# Topologies and links

A `Topology` is named nodes plus a `LinkModel` per edge. It is what the backend
draws entanglement from, and it is where the physics you are testing against lives.

## The default

If you pass no topology, the harness builds one from the application's roles:

- **two roles** → a direct link (`line2`), with the nodes named after the roles;
- **three or more** → a star with `roles()[0]` as the hub, so a multipartite
  protocol fuses the hub's bipartite pairs into a shared GHZ state.

Roles map to nodes *by name*, so a custom topology must contain a node for every
role — otherwise the run raises `ValueError: topology ... is missing nodes for
roles [...]`.

## The link model

```python
from qnetbench.topology import LinkModel

LinkModel(
    attempt_latency=1e-3,   # mean seconds to deliver one pair
    link_fidelity=0.95,     # mean delivered fidelity to |Φ+>
    fidelity_std=0.01,      # spread on that fidelity
)
```

All three fields have defaults, so `LinkModel()` is a usable 0.95-fidelity,
1 ms link. Setting `fidelity_std=0.0` gives a deterministic link, which is what you
want when sweeping fidelity — otherwise you are measuring the spread as well as the
mean.

## Building one

```python
from qnetbench.harness import run_once
from qnetbench.topology import LinkModel, line2, star

# A noisier, slower two-node link:
link = LinkModel(link_fidelity=0.80, attempt_latency=5e-3, fidelity_std=0.02)
run_once("qkd", topology=line2("alice", "bob", link=link))

# A four-node star for a multipartite application (hub first):
run_once("conference_key", topology=star("alice", ["bob", "charlie", "dave"], link=link))
```

Both helpers apply one `LinkModel` to every edge. For a heterogeneous network —
one good link and one bad one — construct the `Topology` directly:

```python
from qnetbench.topology import LinkModel, Topology

topo = Topology(
    name="asymmetric-line3",
    nodes=("alice", "repeater", "bob"),
    links={
        frozenset(("alice", "repeater")): LinkModel(link_fidelity=0.98, attempt_latency=1e-3),
        frozenset(("repeater", "bob")):   LinkModel(link_fidelity=0.85, attempt_latency=8e-3),
    },
)
```

Edges are keyed by `frozenset`, so they are undirected and order does not matter.
`topo.link(a, b)` retrieves one, raising a clear `KeyError` naming the topology if
the edge does not exist.

!!! note "What the backends model today"

    Arbitrary graphs are constructible, but the Phase-0 backends model direct links
    and star/GHZ fusion. General multi-hop routing is on the roadmap; the
    multi-hop applications (`entanglement_swap`, `multihop_qkd`) build their
    end-to-end pair from elementary links explicitly, in the application, rather
    than relying on a routing layer.

## Sweeping the link

This is the pattern behind the fidelity-sensitivity curves — hold everything else
fixed, vary one link parameter, average over seeds:

```python
from qnetbench.harness import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, line2

def utility(app: str, fidelity: float, seeds: range = range(16)) -> float:
    topo = line2(link=LinkModel(attempt_latency=1e-3, link_fidelity=fidelity, fidelity_std=0.0))
    reports = [compute_report(run_once(app, seed=s, topology=topo)) for s in seeds]
    return sum(r.app_utility for r in reports) / len(reports)

for f in (0.70, 0.80, 0.90, 0.95, 1.0):
    print(f, round(utility("qkd", f), 3))
```

[`qnetbench.characterize`](characterization.md) does exactly this, with bisection
refinement around the crossing point and per-seed error reporting — use it rather
than rolling your own if you want the published numbers.

## API

[`LinkModel`, `Topology`, `line2`, `star`](../reference/topology.md).
