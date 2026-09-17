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


def test_singlet_fraction_is_zero_knowledge_of_basis_agreement_alone() -> None:
    """Two bases cannot tell an entangled pair from a classically correlated one.

    A Werner state at F=0.5 is separable, yet agrees with itself in Z and in X
    two times in three. The singlet fraction uses Y as well, which is what makes
    it able to say so.
    """
    from qnetbench.api import Basis
    from qnetbench.apps.purify import singlet_fraction

    # Werner at F: a_Z = a_X = F + (1-F)/3, a_Y = 2(1-F)/3.
    for f in (0.5, 0.75, 1.0):
        zx, y = f + (1 - f) / 3, 2 * (1 - f) / 3
        agree = {
            Basis.Z: (round(zx * 1000), 1000),
            Basis.X: (round(zx * 1000), 1000),
            Basis.Y: (round(y * 1000), 1000),
        }
        assert abs(singlet_fraction(agree) - f) < 2e-3


def test_distillation_claims_nothing_from_separable_pairs() -> None:
    """The regression this metric exists to prevent.

    At F=0.5 the input pairs are separable, so no protocol can distil
    entanglement from them. Scoring by single-basis agreement reported about 0.75
    here and called it a success; the singlet fraction sits at the 1/2 boundary
    and shows no gain over the raw pairs.

    The assertion is on the mean over seeds, not on any single run: the estimator
    is unbiased, so at exactly the boundary it straddles 1/2 and a per-run verdict
    is a coin flip. That is the honest behaviour — one run at F=0.5 genuinely
    cannot tell you whether anything was distilled.
    """
    from qnetbench.apps import get_app
    from qnetbench.characterize.curves import _topology_for
    from qnetbench.harness.runner import run_once
    from qnetbench.metrics import compute_report
    from qnetbench.topology import LinkModel

    roles = get_app("distillation").roles()
    link = LinkModel(attempt_latency=1e-3, link_fidelity=0.5, fidelity_std=0.0)
    utilities, gains = [], []
    for seed in range(12):
        events = run_once("distillation", seed=seed, topology=_topology_for(roles, link))
        utilities.append(compute_report(events).app_utility)
        payload = next(
            e.payload for e in events if getattr(e, "kind", "") == "app_outcome"
        )
        gains.append(payload["distilled_quality"] - payload["raw_quality"])

    mean_utility = sum(utilities) / len(utilities)
    assert mean_utility < 0.60, "must not credit distillation of separable pairs"
    assert mean_utility < 0.70, "single-basis agreement would have reported ~0.75"
    assert sum(gains) / len(gains) < 0.05, "no quality is manufactured at the boundary"


def test_distillation_manufactures_quality_above_the_threshold() -> None:
    """The other half of the claim: above threshold the output beats the input."""
    from qnetbench.apps import get_app
    from qnetbench.characterize.curves import _topology_for
    from qnetbench.harness.runner import run_once
    from qnetbench.metrics import compute_report
    from qnetbench.topology import LinkModel

    roles = get_app("distillation").roles()
    link = LinkModel(attempt_latency=1e-3, link_fidelity=0.9, fidelity_std=0.0)
    utilities = [
        compute_report(
            run_once("distillation", seed=s, topology=_topology_for(roles, link))
        ).app_utility
        for s in range(12)
    ]
    assert sum(utilities) / len(utilities) > 0.9  # better than the 0.9 it was given
