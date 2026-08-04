"""Session-based heralded teleportation.

Beyond correctness, this app exists to occupy a region of the demand space the rest
of the suite does not reach: super-Poissonian (Fano > 1) arrivals. Every other
application's demand is paced either steadily or by a circuit's layer structure,
which makes it *more* regular than random; an idle-then-retry session pattern is
what real user traffic looks like, and it is the regime queueing behaviour is most
sensitive to. The Fano assertion below is what keeps that property from silently
regressing.
"""

from __future__ import annotations

import pytest

from qnetbench.apps import available_apps
from qnetbench.characterize.signature import characterize_trace
from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, line2
from qnetbench.trace.events import AppOutcomeEvent

PERFECT = line2(link=LinkModel(link_fidelity=1.0, fidelity_std=0.0))


@pytest.mark.parametrize("seed", range(6))
def test_noiseless_teleports_are_exact(seed: int) -> None:
    rep = compute_report(run_once("heralded_teleport", seed=seed, topology=PERFECT))
    assert rep.app_success
    assert rep.app_utility == 1.0


def test_failed_heralds_consume_extra_pairs() -> None:
    """A heralded BSM is probabilistic, so a teleport costs a geometric number of
    pairs — that retry cost is the workload, and it must show up in the trace."""
    for seed in range(6):
        events = run_once("heralded_teleport", seed=seed)
        payload = next(e for e in events if isinstance(e, AppOutcomeEvent)).payload
        assert float(payload["pairs_per_teleport"]) > 1.0


def test_demand_is_super_poissonian() -> None:
    """Fano > 1 (bursty). This is the gap in the suite the app was added to fill."""
    fano = [characterize_trace(run_once("heralded_teleport", seed=s)).fano_factor for s in range(4)]
    assert sum(fano) / len(fano) > 1.0


def test_it_is_the_burstiest_app_in_the_suite() -> None:
    """Guards the claim the characterization table makes: no other core protocol
    reaches the super-Poissonian regime, so this one should top the Fano ranking."""
    fano = {app: characterize_trace(run_once(app, seed=0)).fano_factor for app in available_apps()}
    assert max(fano, key=lambda a: fano[a]) == "heralded_teleport"
