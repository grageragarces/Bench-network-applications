# Traces

A run is a stream of events, one JSON object per line. The trace is the durable
artifact of the suite: metrics, demand signatures and figures are all derived from
it, and it is the contract a third-party tool consumes without importing any of our
code.

```bash
qnetbench run qkd --out qkd.jsonl
```

```json
{"t":0.0,"kind":"run_header","schema_version":"0.3.0","api_version":"0.3.0","app":"qkd","backend":"reference","arbitration":"native","topology":"line2","seed":0}
{"t":0.0,"kind":"ent_requested","req_id":0,"src":"alice","dst":"bob","n":1,"demand":{"min_fidelity":0.9,"latency_budget":null,"deadline":null,"staleness_tolerance":null,"priority":1.0,"purpose":"keep"}}
{"t":0.0032935277908098274,"kind":"ent_delivered","req_id":0,"actual_fidelity":0.9410405402361426,"latency":0.0032935277908098274,"pair_age":0.0}
```

## The event types

Every event carries a simulated time `t` in seconds and a `kind` discriminator.

| `kind` | Emitted by | Key fields |
|---|---|---|
| `run_header` | harness | `schema_version`, `api_version`, `app`, `backend`, `arbitration`, `topology`, `seed` |
| `ent_requested` | backend | `req_id`, `src`, `dst`, `n`, `demand` |
| `ent_delivered` | backend | `req_id`, `actual_fidelity`, `latency`, `pair_age` |
| `contract_violation` | backend | `req_id`, `violation` ∈ `fidelity` / `deadline` / `staleness` / `dropped` |
| `classical_msg` | backend | `src`, `dst`, `n_bytes` |
| `qubit_sent` | backend | `src`, `dst`, `fidelity` — single-qubit transmission |
| `measurement` | application | `node`, `basis`, `result` |
| `app_outcome` | application | `role`, `node`, `success`, `utility`, `payload` |

The `demand` object on `ent_requested` is the full contract — `min_fidelity`,
`latency_budget`, `deadline`, `staleness_tolerance`, `priority`, `purpose`. It is
the reason a trace is enough on its own: you can score a delivery against what was
asked for without re-running anything.

## Reading a trace

=== "With qnetbench"

    ```python
    from qnetbench.trace import read_trace
    from qnetbench.trace.events import EntanglementDelivered

    delivered = [e for e in read_trace("qkd.jsonl")
                 if isinstance(e, EntanglementDelivered)]
    print(len(delivered), sum(e.actual_fidelity for e in delivered) / len(delivered))
    ```

    `read_trace` streams and validates against the pydantic models, so a malformed
    line fails loudly instead of quietly producing wrong numbers.

=== "With nothing"

    ```python
    import json

    pairs = fidelity_sum = 0.0
    for line in open("qkd.jsonl"):
        e = json.loads(line)
        if e["kind"] == "ent_delivered":
            pairs += 1
            fidelity_sum += e["actual_fidelity"]
    print("delivered:", pairs, "mean fidelity:", fidelity_sum / pairs)
    ```

    This is the point of the format. A scheduler paper in another language reads
    the workload line by line and never installs the suite.

## Writing a trace

```python
from qnetbench.harness import run_once
from qnetbench.trace import write_trace, TraceWriter

write_trace("run.jsonl", run_once("qkd", seed=0))

# or append incrementally
with open("run.jsonl", "w") as fh:
    writer = TraceWriter(fh)
    for event in run_once("bqc", seed=0):
        writer.write(event)
```

## The published reference corpus

One trace per core application, generated on the reference backend at a fixed seed,
with a manifest recording each file's `sha256` and event count:

```bash
qnetbench corpus              # regenerate into traces/
qnetbench corpus --check      # regenerate here and compare; writes nothing
```

```json
{
  "spec_version": "0.3.0",
  "backend": "reference",
  "seed": 0,
  "environment": {"python": "3.12.16", "numpy": "2.5.4",
                  "platform": "Linux-6.17.8-orbstack-00308-g8f9c941121b1-x86_64-with-glibc2.41",
                  "machine": "x86_64"},
  "traces": [
    {"app": "anonymous_transmission", "file": "anonymous_transmission.jsonl",
     "n_events": 518, "sha256": "a0f8c0b235caf6ab730cbcab558621f6dc2461f0ec375cfa8f831cfeb1239f59"}
  ]
}
```

The committed corpus lives in
[`traces/`](https://github.com/grageragarces/Bench-network-applications/tree/main/traces),
and CI regenerates it on Linux, macOS and Windows. A scheduling study can be run
against the suite's workloads from these files alone, with nothing installed.

## Reproducibility

Every run is deterministic in its seed. How exactly a trace reproduces depends on the
environment:

- **Same environment:** identical byte for byte.
- **Different environment:** the same events in the same order, with floats that can
  differ by rounding. The checksums in the manifest hold only for the environment it
  records.

Measured over 27 applications × 16 seeds (`scripts/paper/reproducibility.py`), on
macOS and Linux, ARM and x86, Python 3.10 and 3.12, and numpy 1.26, 2.2 and 2.5:

- Every one of the 432 traces held the same events everywhere, and the largest relative
  float difference was 1.6e-15.
- Linux runs were byte-identical to one another across architecture, Python and numpy.
- Against the macOS and numpy 2.5 run that produced the published corpus, 350 of 432
  were byte-identical.
- Utility was exactly equal in all but two `clock_sync` traces, which differed by
  1.1e-16.

Windows is covered by the CI check rather than by this measurement.

## Versioning

The schema is semantically versioned and the version travels **inside the data**,
in every trace's `run_header.schema_version`, so a consumer checks compatibility
from the file rather than from your changelog.

- **Patch**: additive and backward compatible — new optional fields, new event
  kinds a reader can ignore.
- **Minor / major before 1.0**: may break. From 1.0 the trace schema is stable and
  a breaking change bumps the major version.

The current version is **0.3.0**, which added `scores` to `app_outcome`. 0.2.0 added
`qubit_sent` for prepare-and-measure protocols.

The JSON Schemas in [`docs/specs/`](../specs/README.md) are generated from the
pydantic models by `qnetbench spec`, and a test regenerates and diffs them — so the
published contract cannot drift from the code.

## API

[`Event` and the event models, `read_trace`, `write_trace`, `TraceWriter`,
`parse_event`, `compare_traces`](../reference/trace.md).
