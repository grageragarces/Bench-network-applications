"""SeQUeNCe backend + cross-backend equivalence.

These are the first cross-backend equivalence checks (Deliverable 1): the same
applications, written once, must satisfy the same outcome invariants whether the
entanglement is supplied by the reference link model or by SeQUeNCe. Physics
differs, so noisy comparisons are asserted as tolerances, not bit-equality.

Skipped unless the optional `sequence` extra is installed.
"""

from __future__ import annotations

import importlib.util

import pytest

from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, line2
from qnetbench.trace.events import AppOutcomeEvent

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("sequence") is None,
    reason="requires the optional 'sequence' extra (pip install qnetbench[sequence])",
)

PERFECT = line2(link=LinkModel(attempt_latency=1e-3, link_fidelity=1.0, fidelity_std=0.0))


def _report(app: str, backend: str, seed: int = 0, topo=None):
    return compute_report(run_once(app, seed=seed, backend=backend, topology=topo or PERFECT))


def test_all_apps_run_on_sequence() -> None:
    for app in ("qkd", "bqc", "distributed_gate"):
        rep = _report(app, "sequence")
        assert rep.backend == "sequence"
        assert rep.n_delivered > 0


def test_sequence_is_deterministic_per_seed() -> None:
    a = run_once("distributed_gate", seed=2, backend="sequence")
    b = run_once("distributed_gate", seed=2, backend="sequence")
    assert [e.model_dump() for e in a] == [e.model_dump() for e in b]


def test_sequence_noiseless_invariants_are_exact() -> None:
    # Same invariants as the reference backend, now supplied by SeQUeNCe.
    assert _report("bqc", "sequence").app_utility == 1.0
    assert _report("distributed_gate", "sequence").app_utility == 1.0
    assert _report("qkd", "sequence").app_success


def test_distributed_gate_truth_table_matches_across_backends() -> None:
    ref = _report("distributed_gate", "reference")
    seq = _report("distributed_gate", "sequence")
    assert ref.app_utility == seq.app_utility == 1.0  # exact CNOT truth table on both


def test_qkd_qber_agrees_across_backends() -> None:
    noisy = line2(link=LinkModel(attempt_latency=1e-3, link_fidelity=0.9, fidelity_std=0.0))

    def qber(backend: str) -> float:
        events = run_once("qkd", seed=0, backend=backend, topology=noisy)
        return max(
            float(e.payload["qber"])  # type: ignore[arg-type]
            for e in events
            if isinstance(e, AppOutcomeEvent)
        )

    theory = 2 * (1 - 0.9) / 3  # ≈ 0.0667
    ref, seq = qber("reference"), qber("sequence")
    assert abs(ref - theory) < 0.05
    assert abs(seq - theory) < 0.05


def test_sequence_reports_realistic_supply() -> None:
    rep = _report("qkd", "sequence")
    assert rep.delivered_rate > 0  # SeQUeNCe-derived generation rate
    assert 0.99 <= rep.mean_fidelity <= 1.0  # noiseless link
