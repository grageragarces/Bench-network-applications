# qnetbench trace & metric specification

**Spec version: 0.2.0** (semantic-versioned; tracks the trace `schema_version`).
0.2.0 added the `qubit_sent` event (single-qubit transmission, for prepare-and-measure
protocols such as BB84).

This directory is the versioned, machine-readable contract a third-party tool —
e.g. a scheduler or routing paper — can consume without importing qnetbench.

| File | What it is |
|---|---|
| [`trace-schema.json`](trace-schema.json) | JSON Schema for a single trace event (the tagged union of event types) |
| [`metric-schema.json`](metric-schema.json) | JSON Schema for the standard metric report |

Both schemas are generated from the pydantic models, so they cannot drift from the
code — a test regenerates and diffs them. Regenerate with `qnetbench spec`.

## Trace format

A run is a stream of JSON objects, **one event per line** (JSONL). Every event has
a `kind` discriminator and a simulated-time `t` (seconds). The event types:

| `kind` | Emitted by | Key fields |
|---|---|---|
| `run_header` | harness | `schema_version`, `api_version`, `app`, `backend`, `arbitration`, `topology`, `seed` |
| `ent_requested` | backend | `req_id`, `src`, `dst`, `n`, `demand` |
| `ent_delivered` | backend | `req_id`, `actual_fidelity`, `latency`, `pair_age` |
| `contract_violation` | backend | `req_id`, `violation` ∈ {fidelity, deadline, staleness, dropped} |
| `classical_msg` | backend | `src`, `dst`, `n_bytes` |
| `qubit_sent` | backend | `src`, `dst`, `fidelity` (single-qubit transmission) |
| `measurement` | app | `node`, `basis`, `result` |
| `app_outcome` | app | `role`, `node`, `success`, `utility`, `payload` |

The `demand` object on `ent_requested` is the contract: `min_fidelity`,
`latency_budget`, `deadline`, `staleness_tolerance`, `priority`, `purpose`.

## Published reference traces

[`../../traces/`](../../traces/) holds one trace per application, generated on the
reference backend at a fixed seed, with a [`manifest.json`](../../traces/manifest.json)
listing each trace's `sha256` and event count. Regenerate with `qnetbench corpus`.

Consume a trace in any language by reading it line-by-line as JSON; the metrics in
[`../design.md §5`](../design.md) are computed purely from these events.

## Stability policy

- **Patch** (0.1.x): additive, backward-compatible (new optional fields, new event
  kinds a reader can ignore).
- **Minor/major** before 1.0 may break; from 1.0 the trace schema is stable and
  breaking changes bump the major version. The version travels in every trace's
  `run_header.schema_version`, so a consumer can check compatibility from the data.
