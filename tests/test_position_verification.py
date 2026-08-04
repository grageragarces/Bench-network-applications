"""Quantum position verification (distance bounding).

The distinguishing property is that the deadline is a physical bound rather than a
performance target: a pair delivered after the round-trip light-travel time cannot
support a sound verification, so a contract violation is a *failed* verification,
not merely a slow one. The tightening test below is what pins that semantics down.
"""

from __future__ import annotations

import pytest

from qnetbench.characterize.signature import characterize_trace
from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, line2
from qnetbench.trace.events import AppOutcomeEvent

_PERFECT = LinkModel(link_fidelity=1.0, fidelity_std=0.0)
PERFECT = line2("verifier", "prover", link=_PERFECT)


def _report(seed: int, topo=PERFECT, cfg=None):
    return compute_report(run_once("position_verification", seed=seed, topology=topo, cfg=cfg))


@pytest.mark.parametrize("seed", range(6))
def test_honest_prover_verifies_noiselessly(seed: int) -> None:
    rep = _report(seed)
    assert rep.app_success
    assert rep.app_utility == 1.0


def test_every_request_carries_a_deadline() -> None:
    sig = characterize_trace(run_once("position_verification", seed=0))
    assert sig.deadline_fraction == 1.0


def test_a_bound_tighter_than_the_link_fails_verification() -> None:
    """Squeeze the response budget below what the link can deliver and verification
    collapses even though the physics is noiseless — late is insecure, not slow."""
    tight = {"response_budget": 1e-5}
    utilities = [_report(s, cfg=tight).app_utility for s in range(6)]
    assert sum(utilities) / len(utilities) < 0.5

    events = run_once("position_verification", seed=0, topology=PERFECT, cfg=tight)
    payload = next(e for e in events if isinstance(e, AppOutcomeEvent)).payload
    assert int(payload["late"]) > 0  # the failures are timing, not correlation
    assert int(payload["wrong"]) == 0


def test_a_slower_link_costs_verifications() -> None:
    """Same budget, slower link: verification degrades because propagation ate it."""
    slow_link = LinkModel(attempt_latency=5e-3, link_fidelity=1.0, fidelity_std=0.0)
    slow = line2("verifier", "prover", link=slow_link)
    fast = [_report(s).app_utility for s in range(6)]
    slow_utils = [_report(s, topo=slow).app_utility for s in range(6)]
    assert sum(slow_utils) / len(slow_utils) < sum(fast) / len(fast)
