"""SeQUeNCe backend + cross-backend equivalence.

The same applications, written once, must satisfy the same outcome invariants
whether entanglement is supplied by the reference link model or by SeQUeNCe.
Physics differs, so noisy comparisons are asserted as tolerances.

Skipped unless the optional `sequence` extra is installed.
"""

from __future__ import annotations

import importlib.util

import pytest

from qnetbench.apps import available_apps
from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, line2, star
from qnetbench.trace.events import AppOutcomeEvent

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("sequence") is None,
    reason="requires the optional 'sequence' extra (pip install qnetbench[sequence])",
)

BACKEND = "sequence"
PERFECT = line2(link=LinkModel(attempt_latency=1e-3, link_fidelity=1.0, fidelity_std=0.0))
_PL = LinkModel(attempt_latency=1e-3, link_fidelity=1.0, fidelity_std=0.0)
PERFECT_STAR = star("charlie", ["alice", "bob"], link=_PL)


def _report(app: str, seed: int = 0, topo=None):
    return compute_report(run_once(app, seed=seed, backend=BACKEND, topology=topo))


def test_all_apps_run_on_backend() -> None:
    for app in available_apps():  # default topology per app
        rep = _report(app)
        assert rep.backend == BACKEND
        assert rep.n_delivered > 0 or rep.qubits_sent > 0  # bb84 transmits qubits, not pairs


def test_backend_is_deterministic_per_seed() -> None:
    a = run_once("distributed_gate", seed=2, backend=BACKEND)
    b = run_once("distributed_gate", seed=2, backend=BACKEND)
    assert [e.model_dump() for e in a] == [e.model_dump() for e in b]


def test_noiseless_invariants_are_exact() -> None:
    assert _report("bqc", topo=PERFECT).app_utility == 1.0
    assert _report("distributed_gate", topo=PERFECT).app_utility == 1.0
    assert _report("anonymous_transmission", topo=PERFECT_STAR).app_utility == 1.0
    assert _report("qkd", topo=PERFECT).app_success
    assert _report("chsh", topo=PERFECT).app_success  # S > 2
    assert _report("clock_sync", topo=PERFECT).app_utility > 0.9
    assert _report("dqc_ghz4", topo=PERFECT).app_utility == 1.0  # mirror circuit -> |0…0>


def test_distributed_gate_truth_table_matches_across_backends() -> None:
    ref = compute_report(run_once("distributed_gate", seed=0, topology=PERFECT))
    sim = _report("distributed_gate", topo=PERFECT)
    assert ref.app_utility == sim.app_utility == 1.0


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
    assert abs(qber("reference") - theory) < 0.05
    assert abs(qber(BACKEND) - theory) < 0.05
