"""B92, six-state QKD (prepare-and-measure) and Byzantine agreement."""

from __future__ import annotations

import pytest

from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, line2, star
from qnetbench.trace.events import EntanglementRequested, QubitSent

PERFECT = line2(link=LinkModel(link_fidelity=1.0, fidelity_std=0.0))


# --- B92 ----------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(6))
def test_b92_succeeds_noiseless(seed: int) -> None:
    assert compute_report(run_once("b92", seed=seed, topology=PERFECT)).app_success


def test_b92_is_prepare_and_measure() -> None:
    events = run_once("b92", seed=0, topology=PERFECT, cfg={"rounds": 40})
    assert sum(1 for e in events if isinstance(e, QubitSent)) == 40
    assert sum(1 for e in events if isinstance(e, EntanglementRequested)) == 0


def test_b92_fails_below_threshold() -> None:
    noisy = line2(link=LinkModel(link_fidelity=0.75, fidelity_std=0.0))
    assert not any(
        compute_report(run_once("b92", seed=s, topology=noisy)).app_success for s in range(6)
    )


# --- six-state ----------------------------------------------------------------


@pytest.mark.parametrize("seed", range(6))
def test_six_state_succeeds_noiseless(seed: int) -> None:
    assert compute_report(run_once("six_state", seed=seed, topology=PERFECT)).app_success


def test_six_state_is_prepare_and_measure() -> None:
    events = run_once("six_state", seed=0, topology=PERFECT, cfg={"rounds": 60})
    assert sum(1 for e in events if isinstance(e, QubitSent)) == 60
    assert sum(1 for e in events if isinstance(e, EntanglementRequested)) == 0


def test_six_state_fails_below_threshold() -> None:
    noisy = line2(link=LinkModel(link_fidelity=0.7, fidelity_std=0.0))
    assert not any(
        compute_report(run_once("six_state", seed=s, topology=noisy)).app_success for s in range(6)
    )


# --- Byzantine agreement ------------------------------------------------------


_PERFECT_STAR = star(
    "general", ["lieutenant1", "lieutenant2"], link=LinkModel(link_fidelity=1.0, fidelity_std=0.0)
)


@pytest.mark.parametrize("seed", range(6))
def test_byzantine_correct_noiseless(seed: int) -> None:
    # Honest generals reach consensus and faulty ones are detected — every round correct.
    report = compute_report(run_once("byzantine_agreement", seed=seed, topology=_PERFECT_STAR))
    assert report.app_utility == 1.0


def test_byzantine_is_three_party() -> None:
    report = compute_report(run_once("byzantine_agreement", seed=0, topology=_PERFECT_STAR))
    assert len(report.roles) == 3
