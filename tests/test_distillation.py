"""Entanglement distillation and the distilled distributed gate.

The distillation invariant is not "it runs" but "it actually purifies": the
distilled pairs must be measurably better correlated than the raw pairs drawn from
the same link in the same run. The distilled-gate invariant adds the property the
suite previously had no example of — a single application emitting two demand
classes, so its deadline fraction is strictly between 0 and 1.
"""

from __future__ import annotations

import pytest

from qnetbench.characterize.signature import characterize_trace
from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, line2
from qnetbench.trace.events import AppOutcomeEvent, EntanglementRequested

PERFECT = line2(link=LinkModel(link_fidelity=1.0, fidelity_std=0.0))


def _payload(app: str, seed: int, topo=None) -> dict:
    events = run_once(app, seed=seed, topology=topo)
    return next(e for e in events if isinstance(e, AppOutcomeEvent)).payload


@pytest.mark.parametrize("seed", range(6))
def test_distillation_noiseless_is_exact(seed: int) -> None:
    rep = compute_report(run_once("distillation", seed=seed, topology=PERFECT))
    assert rep.app_success
    assert rep.app_utility == 1.0


@pytest.mark.parametrize("fidelity", [0.75, 0.85, 0.95])
def test_distillation_improves_on_raw_pairs(fidelity: float) -> None:
    """The point of the protocol: distilled pairs beat the raw pairs feeding them."""
    noisy = line2(link=LinkModel(link_fidelity=fidelity, fidelity_std=0.0))
    raw = []
    distilled = []
    for seed in range(6):
        p = _payload("distillation", seed, noisy)
        raw.append(float(p["raw_quality"]))
        distilled.append(float(p["distilled_quality"]))
    assert sum(distilled) / len(distilled) > sum(raw) / len(raw)


def test_distillation_yield_respects_the_recurrence_ceiling() -> None:
    """Two pairs in, at most one out: yield can never exceed 1/2."""
    for seed in range(6):
        p = _payload("distillation", seed)
        assert 0.0 < float(p["yield"]) <= 0.5


def test_distillation_asks_for_a_low_fidelity_bar() -> None:
    """Its contract is the inverse of every other app's: raw pairs are the input,
    so a high `min_fidelity` would reject exactly what it exists to consume."""
    events = run_once("distillation", seed=0)
    demands = [e.demand for e in events if isinstance(e, EntanglementRequested)]
    assert demands
    assert all(d.min_fidelity <= 0.5 for d in demands)
    assert all(d.staleness_tolerance is not None for d in demands)


@pytest.mark.parametrize("seed", range(6))
def test_distilled_gate_reproduces_cnot_truth_table(seed: int) -> None:
    rep = compute_report(run_once("distilled_gate", seed=seed, topology=PERFECT))
    assert rep.app_success
    assert rep.app_utility == 1.0


def test_distilled_gate_is_mixed_criticality() -> None:
    """The property no other application in the suite has: best-effort bulk demand
    and deadline-bearing gate demand in one workload, so the deadline fraction lands
    strictly between the 0.00 / 1.00 that every other app reports."""
    sig = characterize_trace(run_once("distilled_gate", seed=0))
    assert 0.0 < sig.deadline_fraction < 1.0


def test_distilled_gate_falls_back_when_distillation_fails() -> None:
    """A failed recurrence step still leaves a gate to perform, so the node draws a
    fresh pair under the tight contract. Over a noisy link both paths are taken."""
    noisy = line2(link=LinkModel(link_fidelity=0.85, fidelity_std=0.0))
    distilled = 0
    fallback = 0
    for seed in range(6):
        p = _payload("distilled_gate", seed, noisy)
        distilled += int(p["distilled"])
        fallback += int(p["fallback_pairs"])
    assert distilled > 0
    assert fallback > 0
