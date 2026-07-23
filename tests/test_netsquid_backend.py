"""NetSquid backend + cross-backend equivalence.

The same applications, written once, must satisfy the same outcome invariants
whether entanglement is supplied by the reference link model or by NetSquid.
Physics differs, so noisy comparisons are asserted as tolerances.

Skipped unless the optional `netsquid` extra is installed (NetSquid needs numpy<2,
so it lives in its own environment — see the README).
"""

from __future__ import annotations

import importlib.util

import pytest

from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, line2
from qnetbench.trace.events import AppOutcomeEvent

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("netsquid") is None,
    reason="requires the optional 'netsquid' extra (numpy<2; see README)",
)

PERFECT = line2(link=LinkModel(attempt_latency=1e-3, link_fidelity=1.0, fidelity_std=0.0))


def _report(app: str, backend: str, seed: int = 0, topo=None):
    return compute_report(run_once(app, seed=seed, backend=backend, topology=topo or PERFECT))


def test_all_apps_run_on_netsquid() -> None:
    for app in ("qkd", "bqc", "distributed_gate"):
        rep = _report(app, "netsquid")
        assert rep.backend == "netsquid"
        assert rep.n_delivered > 0


def test_netsquid_is_deterministic_per_seed() -> None:
    a = run_once("distributed_gate", seed=2, backend="netsquid")
    b = run_once("distributed_gate", seed=2, backend="netsquid")
    assert [e.model_dump() for e in a] == [e.model_dump() for e in b]


def test_netsquid_noiseless_invariants_are_exact() -> None:
    assert _report("bqc", "netsquid").app_utility == 1.0
    assert _report("distributed_gate", "netsquid").app_utility == 1.0
    assert _report("qkd", "netsquid").app_success


def test_distributed_gate_truth_table_matches_across_backends() -> None:
    ref = _report("distributed_gate", "reference")
    nsq = _report("distributed_gate", "netsquid")
    assert ref.app_utility == nsq.app_utility == 1.0


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
    ref, nsq = qber("reference"), qber("netsquid")
    assert abs(ref - theory) < 0.05
    assert abs(nsq - theory) < 0.05


def test_netsquid_reports_realistic_supply() -> None:
    rep = _report("qkd", "netsquid")
    assert rep.delivered_rate > 0
    assert 0.99 <= rep.mean_fidelity <= 1.0
