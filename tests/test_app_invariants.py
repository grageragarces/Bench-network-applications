"""Backend-agnostic application invariants.

Today these run against the reference backend, which is the oracle. When the
SeQUeNCe and NetSquid backends land, the same invariants (asserted as tolerances,
since the physics differs) become the cross-backend equivalence suite.
"""

from __future__ import annotations

import pytest

from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, line2
from qnetbench.trace.events import AppOutcomeEvent

PERFECT = line2(link=LinkModel(link_fidelity=1.0, fidelity_std=0.0))


def _report(app: str, seed: int, topo=PERFECT):
    return compute_report(run_once(app, seed=seed, topology=topo))


@pytest.mark.parametrize("seed", range(10))
def test_qkd_noiseless_sifts_without_errors(seed: int) -> None:
    rep = _report("qkd", seed)
    assert rep.app_success
    qbers = [r.utility for r in rep.roles]  # utility is key fraction; both roles agree
    assert all(u > 0 for u in qbers)


def _max_qber(seed: int, topo) -> float:
    events = run_once("qkd", seed=seed, topology=topo)
    qbers = [e.payload["qber"] for e in events if isinstance(e, AppOutcomeEvent)]
    return max(float(q) for q in qbers)  # type: ignore[arg-type]


def test_qkd_fails_below_qber_threshold() -> None:
    noisy = line2(link=LinkModel(link_fidelity=0.7, fidelity_std=0.0))
    # Werner F=0.7 → QBER ≈ 2(1-F)/3 ≈ 0.20, comfortably above the 0.11 threshold.
    qbers = [_max_qber(s, noisy) for s in range(10)]
    assert sum(qbers) / len(qbers) > 0.15
    assert not any(_report("qkd", s, noisy).app_success for s in range(10))


@pytest.mark.parametrize("seed", range(10))
def test_bqc_noiseless_is_exact(seed: int) -> None:
    assert _report("bqc", seed).app_utility == 1.0


@pytest.mark.parametrize("seed", range(10))
def test_distributed_gate_reproduces_cnot_truth_table(seed: int) -> None:
    rep = _report("distributed_gate", seed)
    assert rep.app_success
    assert rep.app_utility == 1.0


def test_fidelity_monotonically_degrades_utility() -> None:
    def mean_util(app: str, fidelity: float) -> float:
        topo = line2(link=LinkModel(link_fidelity=fidelity, fidelity_std=0.0))
        return sum(_report(app, s, topo).app_utility for s in range(15)) / 15

    for app in ("bqc", "distributed_gate"):
        assert mean_util(app, 1.0) >= mean_util(app, 0.85) >= mean_util(app, 0.7)


def test_runs_are_deterministic_per_seed() -> None:
    a = run_once("bqc", seed=3)
    b = run_once("bqc", seed=3)
    assert [e.model_dump() for e in a] == [e.model_dump() for e in b]
