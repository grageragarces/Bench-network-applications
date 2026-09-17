# Backends

An application is written once and never imports a simulator. The **backend** is
what supplies entanglement, applies the physics, and drives simulated time. You
choose it per run; the relevant simulator is imported lazily, so the core install
needs none of them.

```bash
qnetbench run qkd --backend reference   # pure Python, always available
qnetbench run qkd --backend sequence    # entanglement supplied by SeQUeNCe
qnetbench run qkd --backend netsquid    # entanglement supplied by NetSquid
```

| Backend | Install | Notes |
|---|---|---|
| `reference` | included | pure Python; the only one that models pair aging |
| `sequence` | `pip install "qnetbench[sequence]"` | requires **numpy ≥ 2.3.5** |
| `netsquid` | register at [netsquid.org](https://netsquid.org), then `pip install --extra-index-url https://pypi.netsquid.org "qnetbench[netsquid]"` | requires **numpy < 2** |

!!! warning "One virtualenv per simulator"

    SeQUeNCe and NetSquid have contradictory numpy pins and cannot be installed
    together. Use `.venv` for one and `.venv-ns` for the other; see
    [Install](../install.md).

## How the layering works

Only the reference backend implements the execution engine. The simulator backends
are **supply** backends: the external simulator owns entanglement-generation
physics, and qnetbench replays the delivered-pair stream it produces through the
same verified engine.

```text
       application  ──────────────┐   (never imports a simulator)
                                  │
       qnetbench.api  ────────────┤   the portable shim
                                  │
    ┌──────────────────────────────▼──────────────────────────────┐
    │ ReferenceBackend — execution engine, local quantum ops,      │
    │ classical channels, contract checking, trace emission        │
    └──────────────┬───────────────────────────────┬───────────────┘
                   │                               │
          _sample_pairs()                   ReplayBackend
       (its own link model)              replays a Supply from …
                                     ┌───────────┴───────────┐
                                SeQUeNCe                 NetSquid
```

A `Supply` is just three things per edge: the gaps between deliveries, each pair's
fidelity, and the one-way classical delay. That is the entire seam a new simulator
has to fill — see [Extending the suite](../adopting.md#add-a-backend).

## `reference`

Pure Python, no dependencies beyond numpy. It is not a toy: it carries an exact
statevector register for local quantum operations, a discrete-event engine for
simulated time, and the contract checking that produces `contract_violation`
events.

It is the only backend that models **pair aging**, so
[characterization](characterization.md) and the staleness curves run on it:

```python
run_once("distributed_gate", pair_age=2e-3, coherence_time=1e-3)
```

Its link model is the [`LinkModel`](topologies.md) attached to each topology edge:
mean delivery latency, mean delivered fidelity, and the standard deviation of that
fidelity.

## `sequence` and `netsquid`

Both drive the real simulator inside `_make_supply` and extract its delivered-pair
stream. What changes between them is the entanglement-generation physics and its
timing; what does not change is the application, the local quantum operations, the
classical protocol, or the trace schema.

They do **not** model pair aging — asking for `pair_age` on them raises
`NotImplementedError` rather than silently ignoring it.

## Cross-backend equivalence

"Two independent backends or it does not count" is one of the suite's design goals,
and it is tested rather than asserted. Every application invariant that holds on the
reference backend must hold on the others, as a tolerance rather than an equality,
since the physics genuinely differs.

Determinism is what makes this testable at all: link sampling and quantum
measurement draw from **separate** RNG streams, so a replay backend — which draws no
link samples — still lands at the same measurement outcomes for a given seed as the
reference backend does.

!!! note "What the comparison currently shows"

    In the published cross-backend runs both simulators deliver a constant
    fidelity of 0.95 and differ from each other only in timing. The equivalence
    suite therefore demonstrates that an application is portable and that the
    replay seam is outcome-preserving; it is not, at present, evidence of
    independent physics agreeing.

## Choosing one

- **Developing an application, or anything that sweeps**: `reference`. It is fast,
  deterministic, dependency-free, and the only one that models staleness.
- **A claim about a specific network technology's timing**: the simulator whose
  models you trust for it.
- **A portability claim**: run both, and compare.

## API

`ReferenceBackend`, `ReplayBackend` and `Supply` are documented in the
[backends API reference](../reference/backends.md).
