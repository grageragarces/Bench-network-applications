"""Entanglement swapping (multi-hop / relay demand)."""

from __future__ import annotations

import pytest

from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, star
from qnetbench.trace.events import EntanglementRequested

_PERFECT = LinkModel(link_fidelity=1.0, fidelity_std=0.0)
PERFECT = star("repeater", ["alice", "bob"], link=_PERFECT)


def _report(seed: int = 0, topo=PERFECT):
    return compute_report(run_once("entanglement_swap", seed=seed, topology=topo))


@pytest.mark.parametrize("seed", range(6))
def test_swapped_pair_is_correlated_noiseless(seed: int) -> None:
    # A noiseless Bell-state measurement swaps two Φ+ links into one; the end-to-end
    # pair is perfectly correlated, so every round agrees.
    assert _report(seed).app_utility == 1.0


def test_demand_is_two_pairs_per_round() -> None:
    events = run_once("entanglement_swap", seed=0, cfg={"rounds": 10})
    requests = sum(1 for e in events if isinstance(e, EntanglementRequested))
    assert requests == 20  # two elementary links per end-to-end unit


def test_utility_degrades_with_fidelity() -> None:
    def mean(fidelity: float) -> float:
        link = LinkModel(link_fidelity=fidelity, fidelity_std=0.0)
        topo = star("repeater", ["alice", "bob"], link=link)
        return sum(_report(s, topo).app_utility for s in range(6)) / 6

    # Swapping compounds the two links' noise, so utility falls with fidelity.
    assert mean(1.0) >= mean(0.9) >= mean(0.8)
    assert mean(0.8) < 1.0


def test_runs_on_default_topology() -> None:
    # No explicit topology: the harness builds the 3-node star (repeater = hub).
    rep = compute_report(run_once("entanglement_swap", seed=0))
    assert rep.topology.startswith("star")
    assert rep.n_delivered > 0
