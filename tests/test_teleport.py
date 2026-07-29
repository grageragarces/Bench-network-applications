"""Quantum state teleportation."""

from __future__ import annotations

import pytest

from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, line2
from qnetbench.trace.events import EntanglementRequested

PERFECT = line2(link=LinkModel(link_fidelity=1.0, fidelity_std=0.0))


def _report(seed: int = 0, topo=PERFECT):
    return compute_report(run_once("teleportation", seed=seed, topology=topo))


@pytest.mark.parametrize("seed", range(6))
def test_teleportation_is_exact_noiseless(seed: int) -> None:
    assert _report(seed).app_utility == 1.0  # Bob recovers every teleported state


def test_one_pair_per_round() -> None:
    events = run_once("teleportation", seed=0, cfg={"rounds": 10})
    assert sum(1 for e in events if isinstance(e, EntanglementRequested)) == 10


def test_utility_degrades_with_fidelity() -> None:
    def mean(fidelity: float) -> float:
        topo = line2(link=LinkModel(link_fidelity=fidelity, fidelity_std=0.0))
        return sum(_report(s, topo).app_utility for s in range(6)) / 6

    assert mean(1.0) >= mean(0.9) >= mean(0.8)
    assert mean(0.8) < 1.0
