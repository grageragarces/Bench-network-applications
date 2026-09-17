# Load any distributed circuit

The suite's circuit generator is what turns *a program* into *a network workload*:
partition a circuit across two nodes, and every non-local two-qubit gate becomes a
teleported gate — one entanglement request, with a deadline set by that gate's
depth in the circuit. The resulting trace **is** the circuit's Entanglement Demand
Schedule.

That machinery is not restricted to the circuits we ship. Any circuit you can
express — hand-written, generated, or imported from Qiskit or MQT Bench — becomes a
runnable, characterizable, cross-backend network benchmark. This page is the
end-to-end recipe.

## What you are building

```text
  a circuit            partition            the benchmark
  ─────────            ─────────            ─────────────
  H  q0                q0,q2 → alice        local gates run locally
  CX q0,q1     ──▶     q1,q3 → bob    ──▶   non-local gates become
  RZ q1                                     teleported gates, i.e.
  CX q1,q3                                  entanglement requests with
                                            deadline = layer × budget
```

Three things are worth knowing before you start, because each one shapes what you
can load:

1. **Two nodes.** `DQC` partitions across exactly two nodes today, `alice` and
   `bob`. Entries in `partition` must be `0` or `1`; anything else raises
   `ValueError` at construction.
2. **A restricted gate set.** The IR knows `H`, `X`, `Y`, `Z`, `S`, `T`, `RX`,
   `RY`, `RZ`, `CNOT`, `CZ`. Real circuits are transpiled into it — one line, shown
   below.
3. **Verifiability is yours to arrange.** The built-in families are *mirror*
   circuits (`U;U†`) so a noiseless run returns to `|0…0>`. An imported circuit is
   not mirrored, so you either mirror it yourself or use a different success
   criterion.

---

## Path 1 — a circuit that already ships

Six families at sizes 4–10 are already named benchmarks. No code:

```bash
qnetbench list --all | tr ',' '\n' | grep dqc_
qnetbench run dqc_qft8
qnetbench run dqc_hea10 --arbitration policy:edf
```

Or parameterized beyond the catalog's sizes, from Python:

```python
from qnetbench.apps import register_app
from qnetbench.apps.dqc import DQC
from qnetbench.circuits import random_circuit
from qnetbench.harness import run_once
from qnetbench.metrics import compute_report

name = register_app(DQC(random_circuit(12, depth=8, seed=3)))   # "dqc_random12"
print(compute_report(run_once(name, seed=0)).n_requests)
```

`register_app` puts the instance in the catalog so everything that resolves a
benchmark **by name** can find it — `run_once`, `characterize_app`, the contention
experiment. It registers in the importing process only; a benchmark you want on the
command line goes in `_CORE` in `qnetbench/apps/__init__.py`.

---

## Path 2 — build a circuit by hand

Useful when you want a specific demand shape rather than a specific algorithm.

```python
from qnetbench.apps import register_app
from qnetbench.apps.dqc import DQC
from qnetbench.circuits import Circuit, Op, mirror
from qnetbench.harness import run_once
from qnetbench.metrics import compute_report

forward = [
    Op("H", (0,)),
    Op("CNOT", (0, 1)),          # non-local: q0 on alice, q1 on bob
    Op("RZ", (1,), (0.3,)),
    Op("CNOT", (1, 2)),          # non-local again
]

circuit = Circuit(
    n_qubits=3,
    partition=(0, 1, 0),         # alice owns q0 and q2, bob owns q1
    ops=mirror(forward),         # U;U† -> verifiable against |0…0>
    name="handmade",
)

print(circuit.n_nonlocal(), circuit.depth())     # 4 8

name = register_app(DQC(circuit, min_fidelity=0.9, layer_budget=1e-2))
report = compute_report(run_once(name, seed=0))
print(name, report.n_requests, report.app_utility)
```

`mirror()` requires invertible gates — self-inverse (`H`, `X`, `Y`, `Z`, `CNOT`,
`CZ`) or angle-negatable (`RX`, `RY`, `RZ`). Avoid `S` and `T` in circuits you
intend to mirror.

---

## Path 3 — import from Qiskit or MQT Bench

This is the path behind the paper's claim that any partitioned circuit, including
one imported from Qiskit or MQT Bench, becomes a runnable network benchmark.

```bash
pip install "qnetbench[mqt]"
```

### The four steps

A real circuit needs a little preparation, because the IR is deliberately small.

```python
from qiskit import QuantumCircuit, transpile
from qnetbench.circuits import from_qiskit, mirror

# 1. Your circuit, from anywhere.
qc = QuantumCircuit(4)
qc.h(0); qc.cx(0, 1); qc.cx(1, 2); qc.ccx(0, 1, 3)
qc.measure_all()

# 2. Strip measurements — the benchmark measures at the end itself.
qc = qc.remove_final_measurements(inplace=False)

# 3. Transpile into the gate set the IR understands.
BASIS = ["h", "x", "y", "z", "rx", "ry", "rz", "cx", "cz"]
qc = transpile(qc, basis_gates=BASIS, optimization_level=1)

# 4. Convert, and mirror so the run is verifiable.
circuit = from_qiskit(qc, name="toffoli4")
circuit.ops = mirror(circuit.ops)

print(len(circuit.ops), circuit.n_nonlocal(), circuit.depth())
```

Note that `BASIS` deliberately excludes `s` and `t`: both are executable in the IR
but neither can be mirrored, and Qiskit will happily decompose them into `rz`
rotations that can.

### A reusable loader

Worth keeping in your own project:

```python
from qiskit import transpile
from qnetbench.apps import register_app
from qnetbench.apps.dqc import DQC
from qnetbench.circuits import Circuit, from_qiskit, mirror

# Invertible-only basis: no S/T, so the result can always be mirrored.
QNETBENCH_BASIS = ["h", "x", "y", "z", "rx", "ry", "rz", "cx", "cz"]


def load_benchmark(qc, name, *, partition=None, make_mirror=True, **dqc_kwargs):
    """Turn a Qiskit circuit into a registered qnetbench benchmark; return its name."""
    qc = qc.remove_final_measurements(inplace=False)
    qc = transpile(qc, basis_gates=QNETBENCH_BASIS, optimization_level=1)

    circuit = from_qiskit(qc, partition=partition, name=name)
    if make_mirror:
        circuit = Circuit(circuit.n_qubits, circuit.partition,
                          mirror(circuit.ops), name=name)
    return register_app(DQC(circuit, **dqc_kwargs), replace=True)
```

```python
from qiskit import QuantumCircuit
from qnetbench.harness import run_once
from qnetbench.metrics import compute_report, render

qc = QuantumCircuit(6)
qc.h(range(6))
for i in range(5):
    qc.cx(i, i + 1)

name = load_benchmark(qc, "myalgo6", min_fidelity=0.9, layer_budget=5e-3)
print(name)                                   # "dqc_myalgo6"
print(render(compute_report(run_once(name, seed=0))))
```

`DQC` prefixes its circuit's name with `dqc_`, which is why `load_benchmark`
returns the registered name rather than expecting you to reconstruct it.

!!! tip "Set `min_fidelity` below your link's fidelity"

    The default link delivers 0.95. A benchmark asking for `min_fidelity=0.95`
    against it records a fidelity violation on roughly half its deliveries by
    construction, which is a fine thing to test deliberately and a confusing thing
    to hit by accident.

### From MQT Bench

MQT Bench hands you a Qiskit circuit, so it goes through the same loader:

```python
from mqt.bench import BenchmarkLevel, get_benchmark

qc = get_benchmark("ghz", BenchmarkLevel.ALG, 8)   # MQT Bench 2.x
name = load_benchmark(qc, "mqt_ghz8")              # -> "dqc_mqt_ghz8"
```

!!! note "MQT Bench's API moves between major versions"

    The call above is MQT Bench 2.x, which takes a `BenchmarkLevel` enum; 1.x took
    keyword arguments and a string level (`get_benchmark(benchmark_name="ghz",
    level="alg", circuit_size=8)`). Either way it returns a Qiskit
    `QuantumCircuit`, and that is the only part `load_benchmark` depends on.

---

## Choosing the partition

The partition is not a detail; it *is* the workload. The same circuit split two
ways is two different network benchmarks.

```python
from qnetbench.circuits import Circuit, ghz

ghz(6).partition       # (0, 1, 0, 1, 0, 1) — the default, interleaved
ghz(6).n_nonlocal()    # 10 entanglement requests

contiguous = Circuit(6, (0, 0, 0, 1, 1, 1), ghz(6).ops, name="ghz6_split")
contiguous.n_nonlocal()    # 2 — a single cut
```

| Partition | Build it with | What it models |
|---|---|---|
| Interleaved (default) | `tuple(q % 2 for q in range(n))` | the stress case: nearest-neighbour gates all cross the network |
| Contiguous halves | `tuple(0 if q < n // 2 else 1 for q in range(n))` | a compiler that minimised the cut |
| Your own | any tuple of `0`/`1` | a specific mapping you care about |

Pass one explicitly as `from_qiskit(qc, partition=...)` or when constructing a
`Circuit`. Comparing the same algorithm across partitions is a clean experiment in
its own right — the circuit is fixed, so everything that changes in the trace is
attributable to the cut.

---

## Verifying an imported circuit

The mirror trick gives you a success criterion for free, but it is not the only
option.

| Strategy | How | When |
|---|---|---|
| **Mirror** (recommended) | `circuit.ops = mirror(circuit.ops)` — noiseless run returns `|0…0>`, utility is the fraction of qubits reading 0 | almost always; it is what the built-in families do |
| **Compare against a local run** | run the same circuit with a trivial partition (`(0,) * n`, no entanglement demand) at fidelity 1.0 and compare outcome distributions | when mirroring would change the algorithm you care about |
| **Demand-only** | ignore utility; read `n_requests`, the arrival pattern, and the deadline distribution out of the trace | when you only want the demand schedule, e.g. to feed a scheduler |

!!! warning "What a mirror success proves"

    A mirror circuit can return to `|0…0>` because the second half undid an error
    the first half introduced. A success means **the entanglement demands were
    met** — not that every teleported gate was individually correct. For a
    demand-schedule benchmark that is the right bar; a fidelity benchmark would
    need a stronger one.

---

## What you get once it is registered

A loaded circuit is an ordinary benchmark. Everything in the suite applies to it.

```python
name = load_benchmark(qc, "myalgo6")
```

=== "Report"

    ```python
    from qnetbench.harness import run_once
    from qnetbench.metrics import compute_report, render

    print(render(compute_report(run_once(name, seed=0))))
    ```

=== "Trace"

    ```python
    from qnetbench.trace import write_trace
    write_trace("myalgo6.jsonl", run_once(name, seed=0))
    ```

    The `ent_requested` events, in order, are the circuit's Entanglement Demand
    Schedule — including each gate's derived deadline in its `demand`.

=== "Characterize"

    ```python
    from qnetbench.characterize import characterize_app, render_table

    signature, curves = characterize_app(name, seeds=range(8))
    print(render_table([signature]))
    ```

    Your circuit now has a measured demand signature on the same axes as every
    other application in the suite — burstiness, classical coupling,
    deadline-criticality, fidelity threshold, staleness half-life.

=== "Policies and backends"

    ```python
    for arb in ("native", "policy:fifo", "policy:edf", "policy:fidelity_first"):
        r = compute_report(run_once(name, seed=0, arbitration=arb))
        print(arb, round(r.app_utility, 3), r.violations)

    compute_report(run_once(name, seed=0, backend="sequence"))   # needs the extra
    ```

=== "Physics"

    ```python
    from qnetbench.topology import LinkModel, line2

    for f in (1.0, 0.95, 0.9, 0.8):
        topo = line2("alice", "bob", link=LinkModel(link_fidelity=f, fidelity_std=0.0))
        print(f, round(compute_report(run_once(name, topology=topo)).app_utility, 3))
    ```

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ValueError: unsupported gate 'ccx'` | the circuit was not transpiled — run `transpile(qc, basis_gates=QNETBENCH_BASIS)` |
| `ValueError: unsupported gate 'measure'` | mid-circuit measurement; `remove_final_measurements` only strips terminal ones. Remove them, or cut the circuit before them |
| `ValueError: unsupported gate 'barrier'` | strip barriers (`transpile` removes them at `optimization_level>=1`, or use `qc.remove_barriers()` where available) |
| `ValueError: gate 'S' is not invertible in this IR` | `mirror()` on a circuit containing `S`/`T` — transpile without them, as `QNETBENCH_BASIS` does |
| `ValueError: DQC currently supports 2-node (alice/bob) partitions only` | a `partition` entry other than `0` or `1` |
| `KeyError: app 'dqc_x' is already registered` | re-registering the same name; pass `replace=True` |
| `KeyError: unknown app 'dqc_x'` | `run_once` ran before `register_app`, or in a different process |
| Utility is not 1.0 on a perfect link | the circuit was not mirrored, or it contains gates whose inverse the IR cannot express |
| The run is very slow | the reference backend carries an exact statevector; cost grows exponentially in qubits *per node*. Stay near the catalog's 4–10 range |

---

## Limits, honestly

- **Two nodes.** Partitions are `{0, 1}`. Multi-node DQC needs the multi-hop
  routing layer that is on the roadmap.
- **No classical control flow.** The IR is a gate list: no mid-circuit measurement,
  feed-forward, or conditionals.
- **No `SWAP`, no multi-controlled gates natively** — transpilation handles them by
  decomposition, which changes the gate count and therefore the demand. That is
  faithful (a network really does pay for the decomposition), but it means the
  demand you measure is the demand of the *transpiled* circuit. Report the basis
  you used.
- **Exact statevector simulation** on the reference backend bounds practical size.

## See also

- [Circuits](../guide/circuits.md) — the IR and the built-in families in detail
- [Applications](../guide/applications.md) — the catalog your benchmark joins
- [Characterization](../guide/characterization.md) — what the demand signature measures
- [`qnetbench.circuits` API](../reference/circuits.md)
