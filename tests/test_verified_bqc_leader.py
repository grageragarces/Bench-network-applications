"""Verified BQC (trap-based) and 5-party leader election."""

from __future__ import annotations

import pytest

from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, line2, star
from qnetbench.trace.events import EntanglementRequested

_PL = LinkModel(link_fidelity=1.0, fidelity_std=0.0)
PERFECT_LINE = line2(link=_PL)
PERFECT_STAR5 = star("node0", ["node1", "node2", "node3", "node4"], link=_PL)


def _util(app: str, seed: int, topo) -> float:
    return compute_report(run_once(app, seed=seed, topology=topo)).app_utility


# --- verified BQC -------------------------------------------------------------


@pytest.mark.parametrize("seed", range(6))
def test_verified_bqc_accepts_noiseless(seed: int) -> None:
    rep = compute_report(run_once("verified_bqc", seed=seed, topology=PERFECT_LINE))
    assert rep.app_success and rep.app_utility == 1.0  # every trap passes -> accept


def test_verified_bqc_rejects_under_noise() -> None:
    noisy = line2(link=LinkModel(link_fidelity=0.8, fidelity_std=0.0))
    # A failed trap rejects the whole computation, so acceptance is rare under noise.
    accepts = sum(
        compute_report(run_once("verified_bqc", seed=s, topology=noisy)).app_success
        for s in range(8)
    )
    assert accepts < 8


# --- leader election (5-party) ------------------------------------------------


@pytest.mark.parametrize("seed", range(4))
def test_leader_election_consistent_noiseless(seed: int) -> None:
    assert _util("leader_election", seed, PERFECT_STAR5) == 1.0


def test_leader_election_is_five_party() -> None:
    rep = compute_report(run_once("leader_election", seed=0, topology=PERFECT_STAR5))
    assert len(rep.roles) == 5  # the highest party count in the suite


def test_leader_election_demand_scales_with_parties() -> None:
    events = run_once("leader_election", seed=0, topology=PERFECT_STAR5, cfg={"elections": 2})
    # 2 elections x 3 bits x 4 leaf pairs.
    assert sum(1 for e in events if isinstance(e, EntanglementRequested)) == 24
