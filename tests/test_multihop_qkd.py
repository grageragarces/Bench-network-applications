"""Multi-hop QKD over a repeater chain and measure-purpose shared randomness."""

from __future__ import annotations

import pytest

from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, line2, star
from qnetbench.trace.events import AppOutcomeEvent, EntanglementRequested

_PL = LinkModel(link_fidelity=1.0, fidelity_std=0.0)
PERFECT_STAR = star("repeater", ["alice", "bob"], link=_PL)
PERFECT_LINE = line2(link=_PL)


# --- multi-hop QKD ------------------------------------------------------------


@pytest.mark.parametrize("seed", range(5))
def test_multihop_qkd_succeeds_noiseless(seed: int) -> None:
    rep = compute_report(run_once("multihop_qkd", seed=seed, topology=PERFECT_STAR))
    assert rep.app_success  # noiseless swap -> zero QBER -> a secure key


def test_multihop_qkd_demand_is_two_pairs_per_round() -> None:
    events = run_once("multihop_qkd", seed=0, topology=PERFECT_STAR, cfg={"rounds": 20})
    assert sum(1 for e in events if isinstance(e, EntanglementRequested)) == 40


def test_multihop_qkd_fails_below_threshold() -> None:
    noisy = star("repeater", ["alice", "bob"], link=LinkModel(link_fidelity=0.75, fidelity_std=0.0))
    # Swapping compounds both links' noise, so QBER clears the threshold well before F=0.5.
    assert not any(
        compute_report(run_once("multihop_qkd", seed=s, topology=noisy)).app_success
        for s in range(5)
    )


# --- shared randomness (purpose="measure") ------------------------------------


@pytest.mark.parametrize("seed", range(5))
def test_shared_randomness_agrees_noiseless(seed: int) -> None:
    rep = compute_report(run_once("shared_randomness", seed=seed, topology=PERFECT_LINE))
    assert rep.app_utility == 1.0  # Z-measured Φ+ gives both sides the same bit


def test_shared_randomness_uses_measure_purpose() -> None:
    # No measurement events are recorded by the app: the backend measures on delivery.
    events = run_once("shared_randomness", seed=0, topology=PERFECT_LINE, cfg={"rounds": 16})
    requests = [e for e in events if isinstance(e, EntanglementRequested)]
    assert requests and all(e.demand.purpose == "measure" for e in requests)


def test_shared_randomness_degrades_with_fidelity() -> None:
    def mean(fidelity: float) -> float:
        topo = line2(link=LinkModel(link_fidelity=fidelity, fidelity_std=0.0))
        outs = [
            e.utility
            for s in range(5)
            for e in run_once("shared_randomness", seed=s, topology=topo)
            if isinstance(e, AppOutcomeEvent)
        ]
        return sum(outs) / len(outs)

    assert mean(1.0) >= mean(0.9) >= mean(0.8)
