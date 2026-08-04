"""1-out-of-2 quantum oblivious transfer.

Correctness is that Bob recovers the secret he chose. The property worth asserting
alongside it is the *security* one that makes OT a distinct protocol class: the
secret he did not choose must remain at chance, because his bits on that index set
were measured in the wrong bases and its parity is uniformly random to him.
"""

from __future__ import annotations

import pytest

from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, line2
from qnetbench.trace.events import AppOutcomeEvent

PERFECT = line2(link=LinkModel(link_fidelity=1.0, fidelity_std=0.0))


def _bob_payload(seed: int, topo=PERFECT) -> dict:
    events = run_once("oblivious_transfer", seed=seed, topology=topo)
    outcomes = [e for e in events if isinstance(e, AppOutcomeEvent)]
    return next(e.payload for e in outcomes if e.role == "bob")


@pytest.mark.parametrize("seed", range(6))
def test_receiver_recovers_the_chosen_secret(seed: int) -> None:
    rep = compute_report(run_once("oblivious_transfer", seed=seed, topology=PERFECT))
    assert rep.app_success
    assert rep.app_utility == 1.0


def test_the_other_secret_stays_at_chance() -> None:
    """Obliviousness: Bob's parity over the mismatched-basis set carries no
    information, so guessing the unchosen secret should be a coin flip."""
    guessed = 0
    total = 0
    for seed in range(12):
        p = _bob_payload(seed)
        guessed += int(p["other_guessed"])
        total += int(p["transfers"])
    rate = guessed / total
    assert 0.3 < rate < 0.7, f"unchosen secret recovered at {rate:.2f}, expected ~0.5"


def test_it_transmits_qubits_rather_than_sharing_pairs() -> None:
    """Like the prepare-and-measure key protocols, its demand is single-qubit
    transmission — no entangled pair is ever shared."""
    rep = compute_report(run_once("oblivious_transfer", seed=0))
    assert rep.qubits_sent > 0
    assert rep.n_delivered == 0


def test_a_noisy_channel_degrades_the_transfer() -> None:
    noisy = line2(link=LinkModel(link_fidelity=0.85, fidelity_std=0.0))
    utils = [
        compute_report(run_once("oblivious_transfer", seed=s, topology=noisy)).app_utility
        for s in range(6)
    ]
    assert sum(utils) / len(utils) < 1.0
