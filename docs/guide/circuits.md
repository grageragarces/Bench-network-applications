# Circuits

`qnetbench.circuits` is a small distributed-circuit intermediate representation. Its
purpose is to turn a *program* into a *network workload*: partition a circuit
across nodes, and every non-local two-qubit gate becomes a teleported gate — one
entanglement request, with a deadline derived from the gate's depth in the circuit.

The trace of a distributed circuit **is** that circuit's Entanglement Demand
Schedule. The demand comes from real program structure rather than from a
hand-set contract, which is what makes the DQC benchmarks different in kind from
the rest of the suite.

!!! tip "Looking for the how-to?"

    This page is the reference for the IR and the built-in families. To load your
    own circuit — including from Qiskit or MQT Bench — follow
    [Load any distributed circuit](../tutorials/distributed-circuits.md).

## The IR

A `Circuit` is qubits assigned to nodes, plus a list of operations:

```python
from qnetbench.circuits import Circuit, Op

circuit = Circuit(
    n_qubits=4,
    partition=(0, 1, 0, 1),        # partition[q] = index of the node owning qubit q
    ops=[Op("H", (0,)), Op("CNOT", (0, 1)), Op("RZ", (1,), (0.3,))],
    name="example",
)
```

An `Op` is a gate name, the qubit indices it acts on, and its parameters.

| Set | Gates |
|---|---|
| One-qubit | `H`, `X`, `Y`, `Z`, `S`, `T`, `RX`, `RY`, `RZ` |
| Two-qubit | `CNOT`, `CZ` |

A `Circuit` answers the questions the demand schedule needs:

```python
circuit.is_nonlocal(circuit.ops[1])   # True: qubits 0 and 1 are on different nodes
circuit.layers()                      # ASAP layer (1-indexed) of each op
circuit.depth()                       # 3
circuit.n_nonlocal()                  # 1 -> exactly one entanglement request
```

`layers()` is an as-soon-as-possible schedule: a gate sits one layer after the
latest gate on any of its qubits. The DQC application turns a non-local gate's
layer into its deadline — `layer × layer_budget` — so deeper gates are due later
and the demand inherits the circuit's dependency structure.

## The partition decides the demand

The same circuit under a different partition is a different network workload. The
built-in families use an **interleaved** partition (`q % 2`), which makes
nearest-neighbour gates non-local and so maximises entanglement demand:

```python
from qnetbench.circuits import Circuit, ghz

ghz(6).partition                       # (0, 1, 0, 1, 0, 1) — interleaved
ghz(6).n_nonlocal()                    # 10

contiguous = Circuit(6, (0, 0, 0, 1, 1, 1), ghz(6).ops, name="ghz6_split")
contiguous.n_nonlocal()                # 2 — one cut instead of five
```

Interleaved is the stress case; a contiguous split is closer to what a compiler
would choose. Both are legitimate benchmarks of different things.

## Mirror circuits

Library circuits are built as **mirror circuits**: a forward unitary `U` followed by
its exact inverse `U†`. A noiseless run therefore returns to `|0…0>` and every
qubit measures 0, which gives every generated instance a well-defined success
criterion without needing a reference simulation to compare against. Utility is the
fraction of qubits that read 0, and it degrades cleanly as teleported-gate fidelity
drops.

```python
from qnetbench.circuits import Op, mirror

mirror([Op("H", (0,)), Op("CNOT", (0, 1))])
# [H(0), CNOT(0,1), CNOT(0,1), H(0)]  — reversed, each op inverted
```

Gates must be invertible within the IR: self-inverse (`H`, `X`, `Y`, `Z`, `CNOT`,
`CZ`) or invertible by angle negation (`RX`, `RY`, `RZ`). `S` and `T` are
executable but not mirrorable, so avoid them in circuits you intend to mirror —
`inverse_op` raises a clear `ValueError` if you don't.

!!! warning "What the mirror criterion does and does not prove"

    A mirror circuit can return to `|0…0>` because the second half undid an error
    the first half introduced. A success is evidence that **the entanglement
    demands were met**, not a certificate that every teleported gate was correct.
    For a demand-schedule benchmark that is the right bar — what is under test is
    the network's ability to supply the pairs the circuit asked for. A fidelity
    benchmark would need a stronger criterion.

## The built-in families

```python
from qnetbench.circuits import ghz, qft, random_circuit, graph_state, iqp, hea
```

| Family | Call | Structure | 4 qubits: ops / non-local / depth |
|---|---|---|---|
| GHZ | `ghz(n)` | `H` + CNOT chain | 8 / 6 / 8 |
| QFT | `qft(n)` | `H` + controlled phases, decomposed to CNOT + RZ | 68 / 16 / 44 |
| Random | `random_circuit(n, depth, seed)` | random single-qubit gates + disjoint CNOT layers | 72 / 20 / 24 |
| Graph state | `graph_state(n)` | `H` on all + CZ around a ring | 16 / 8 / 10 |
| IQP | `iqp(n, seed)` | `H` · diagonal · `H` | 30 / 6 / 12 |
| HEA | `hea(n, depth, seed)` | RY rotations + CNOT entangling layers | 42 / 18 / 20 |

All are mirrored, so the counts above include both halves. Demand grows quickly
with size — `qft(4)` asks for 16 pairs, `qft(10)` asks for 100:

```python
[qft(n).n_nonlocal() for n in (4, 6, 8, 10)]   # [16, 36, 64, 100]
```

Each family at sizes 4–10 is a named catalog entry (`dqc_qft8`, `dqc_hea10`, …) —
see [Applications](applications.md).

## Making a benchmark from a circuit

`DQC` wraps a circuit as an application:

```python
from qnetbench.apps.dqc import DQC
from qnetbench.circuits import qft

app = DQC(qft(6), min_fidelity=0.9, layer_budget=1e-2)
app.name          # "dqc_qft6"
app.roles()       # ['alice', 'bob']
```

| Parameter | Default | Effect |
|---|---|---|
| `min_fidelity` | `0.9` | the fidelity floor in every teleported gate's `Demand` |
| `layer_budget` | `1e-2` | seconds per circuit layer; a gate in layer `k` gets deadline `k × layer_budget` |

Every request also carries `staleness_tolerance=1e-3` and `purpose="keep"`.
Lowering `layer_budget` tightens every deadline at once, which is the knob for
making a circuit deadline-critical.

!!! note "Two nodes today"

    `DQC` currently supports two-node partitions only — `partition` entries must be
    `0` or `1`, mapping to roles `alice` and `bob`. A wider partition raises
    `ValueError` at construction.

## Importing from Qiskit

`from_qiskit(qc)` converts a Qiskit `QuantumCircuit` — including anything from MQT
Bench — into this IR. It needs the `mqt` extra, is not mirrored, and only accepts
the gate set above, so real circuits are usually transpiled first. The complete
recipe is in [Load any distributed circuit](../tutorials/distributed-circuits.md).

## API

[`Circuit`, `Op`, `mirror`, `inverse_op`, the families, `from_qiskit`](../reference/circuits.md).
