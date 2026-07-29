"""Quantum secret sharing and conference key agreement (multipartite protocols)."""

from __future__ import annotations

import pytest

from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, star

_PL = LinkModel(link_fidelity=1.0, fidelity_std=0.0)
PERFECT_SS = star("dealer", ["player1", "player2"], link=_PL)
PERFECT_CK = star("hub", ["leaf1", "leaf2", "leaf3"], link=_PL)


def _report(app: str, seed: int, topo):
    return compute_report(run_once(app, seed=seed, topology=topo))


# --- (n,n) quantum secret sharing ---------------------------------------------


@pytest.mark.parametrize("seed", range(6))
def test_secret_sharing_reconstructs_noiseless(seed: int) -> None:
    assert _report("secret_sharing", seed, PERFECT_SS).app_utility == 1.0


def test_secret_sharing_is_three_party() -> None:
    assert len(_report("secret_sharing", 0, PERFECT_SS).roles) == 3


def test_secret_sharing_degrades_with_fidelity() -> None:
    def mean(fidelity: float) -> float:
        link = LinkModel(link_fidelity=fidelity, fidelity_std=0.0)
        topo = star("dealer", ["player1", "player2"], link=link)
        return sum(_report("secret_sharing", s, topo).app_utility for s in range(6)) / 6

    assert mean(1.0) >= mean(0.9) >= mean(0.8)


# --- conference key agreement (4-party) ---------------------------------------


@pytest.mark.parametrize("seed", range(6))
def test_conference_key_agrees_noiseless(seed: int) -> None:
    assert _report("conference_key", seed, PERFECT_CK).app_utility == 1.0


def test_conference_key_is_four_party() -> None:
    assert len(_report("conference_key", 0, PERFECT_CK).roles) == 4  # highest party count


def test_conference_key_demand_is_three_pairs_per_round() -> None:
    from qnetbench.trace.events import EntanglementRequested

    events = run_once("conference_key", seed=0, topology=PERFECT_CK, cfg={"rounds": 10})
    assert sum(1 for e in events if isinstance(e, EntanglementRequested)) == 30
