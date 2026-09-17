# Command line

Installing the package puts a single `qnetbench` executable on your path, with six
subcommands. Each one is a thin wrapper over a Python entry point, so anything the
CLI does is also available from a script — the Python equivalent is given under
each command.

```console
$ qnetbench --help
usage: qnetbench [-h] {run,list,characterize,spec,corpus,contention} ...

positional arguments:
  {run,list,characterize,spec,corpus,contention}
    run                 run one application and print its report
    list                list available apps and policies
    characterize        measure demand signatures (one app, or all core apps)
    spec                write the versioned trace + metric JSON Schemas
    corpus              write the published reference traces + manifest
    contention          run the multi-tenant cross-policy evaluation (the
                        ranking-inversion result)
```

---

## `qnetbench run`

Execute one benchmark and print its report.

```console
$ qnetbench run --help
usage: qnetbench run [-h] [--backend BACKEND] [--arbitration ARBITRATION]
                     [--seed SEED] [--out OUT] [--json]
                     APP
```

| Option | Default | Meaning |
|---|---|---|
| `APP` | — | any name from `qnetbench list --all` |
| `--backend` | `reference` | `reference`, `sequence`, or `netsquid` |
| `--arbitration` | `native` | `native`, or `policy:fifo` / `policy:fidelity_first` / `policy:edf` |
| `--seed` | `0` | seeds every RNG in the run; runs are deterministic in it |
| `--out PATH` | — | also write the run's JSONL trace to `PATH` |
| `--json` | off | print the report as JSON instead of the text rendering |

```bash
qnetbench run qkd
qnetbench run bqc --arbitration policy:edf
qnetbench run dqc_qft8 --backend sequence --seed 3
qnetbench run distributed_gate --out run.jsonl --json
```

An unknown app name exits `2` with the list hint on stderr; an unknown backend or a
missing simulator extra raises with the install command you need.

=== "Python"

    ```python
    from qnetbench.harness import run_once
    from qnetbench.metrics import compute_report, render

    events = run_once("bqc", seed=0, backend="reference", arbitration="policy:edf")
    print(render(compute_report(events)))
    ```

See [Running benchmarks](running.md) for the arguments `run_once` accepts that the
CLI does not expose (custom topologies, per-run config, pair aging).

---

## `qnetbench list`

Print the available benchmarks and policies.

```bash
qnetbench list          # the 27 core protocols
qnetbench list --all    # the full 66-entry catalog
```

The **core** is the set of distinct protocols that CI, the reference corpus and the
cross-backend equivalence suite all iterate. The **catalog** adds the generated
distributed-circuit instances; every catalog entry is runnable by name. See
[Applications](applications.md).

=== "Python"

    ```python
    from qnetbench.apps import available_apps, catalog_apps
    from qnetbench.policies import available_policies

    len(available_apps())   # 27
    len(catalog_apps())     # 66
    available_policies()    # ['edf', 'fidelity_first', 'fifo']
    ```

---

## `qnetbench characterize`

Measure demand signatures and print the cross-application table.

```console
$ qnetbench characterize --help
usage: qnetbench characterize [-h] [--seeds SEEDS] [--out OUT] [--latex] [APP]
```

| Option | Default | Meaning |
|---|---|---|
| `APP` | all core apps | characterize just this one |
| `--seeds N` | `32` | seeds averaged per sweep point |
| `--out DIR` | — | write per-app signature + curve JSON, `table.txt`, `table.tex`, and a provenance `manifest.json` |
| `--latex` | off | print the table as a booktabs `tabular` |

```bash
qnetbench characterize qkd              # one app, fast
qnetbench characterize                  # all 27 (minutes: it sweeps fidelity and age)
qnetbench characterize --out sig/       # + machine-readable curves and tables
```

!!! tip "This one is slow on purpose"

    Characterizing all 27 applications runs each of them across a swept fidelity
    range and a swept pair age, at 32 seeds per point, with bisection refinement
    around each crossing. Use `--seeds 4` while iterating, and the default for
    anything you intend to publish.

Writing to `--out` stamps the directory with a manifest *before* the run, so a run
that dies half way leaves a manifest saying so rather than a directory that looks
finished. See [Characterization](characterization.md).

=== "Python"

    ```python
    from qnetbench.characterize import characterize_app, render_table

    signature, curves = characterize_app("qkd", seeds=range(8))
    print(render_table([signature]))
    ```

---

## `qnetbench spec`

Regenerate the versioned trace and metric JSON Schemas from the pydantic models.

```bash
qnetbench spec                  # writes into docs/specs/
qnetbench spec --out /tmp/spec
```

The schemas are generated, never hand-written, and a test regenerates and diffs
them — so the committed contract cannot drift from the code. See the
[trace and metric spec](../specs/README.md).

=== "Python"

    ```python
    from qnetbench.spec import trace_json_schema, metric_json_schema, write_specs

    write_specs("docs/specs")
    ```

---

## `qnetbench corpus`

Run every core application once and write the published reference traces plus a
checksummed manifest.

```bash
qnetbench corpus                        # writes into traces/
qnetbench corpus --out /tmp/corpus --seed 1
```

The manifest records the spec version, the seed, and each trace's `sha256` and
event count. This is what lets a third-party scheduler paper consume the suite's
workloads without installing anything. See [Traces](traces.md).

=== "Python"

    ```python
    from qnetbench.spec import generate_reference_corpus

    manifest = generate_reference_corpus("traces", seed=0)
    ```

---

## `qnetbench contention`

Run the multi-tenant cross-policy evaluation — the ranking-inversion result.

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

Takes no options. To vary the mixes, capacity, or burstiness, drive
[`qnetbench.contention`](contention.md) from Python.

=== "Python"

    ```python
    from qnetbench.contention import default_experiment, render_experiment

    print(render_experiment(default_experiment()))
    ```

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | success |
| `2` | unknown application name (the message names `list --all`) |

Anything else propagates as a Python traceback — a missing simulator extra, an
unknown backend, or a topology that lacks a node an application's roles need.
