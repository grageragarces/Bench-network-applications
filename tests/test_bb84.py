"""Prepare-and-measure BB84 and the single-qubit-transmission primitive."""

from __future__ import annotations

import pytest

from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, line2
from qnetbench.trace.events import EntanglementRequested, QubitSent

PERFECT = line2(link=LinkModel(link_fidelity=1.0, fidelity_std=0.0))


def _max_qber(seed: int, topo) -> float:
    from qnetbench.trace.events import AppOutcomeEvent

    events = run_once("bb84", seed=seed, topology=topo)
    return max(float(e.payload["qber"]) for e in events if isinstance(e, AppOutcomeEvent))  # type: ignore[arg-type]


@pytest.mark.parametrize("seed", range(6))
def test_bb84_succeeds_noiseless(seed: int) -> None:
    rep = compute_report(run_once("bb84", seed=seed, topology=PERFECT))
    assert rep.app_success  # zero QBER -> a secure key


def test_bb84_uses_qubit_transmission_not_pairs() -> None:
    events = run_once("bb84", seed=0, topology=PERFECT, cfg={"rounds": 32})
    sent = sum(1 for e in events if isinstance(e, QubitSent))
    pairs = sum(1 for e in events if isinstance(e, EntanglementRequested))
    assert sent == 32  # one qubit transmitted per round
    assert pairs == 0  # prepare-and-measure shares no entanglement


def test_bb84_reports_qubits_sent() -> None:
    rep = compute_report(run_once("bb84", seed=0, topology=PERFECT, cfg={"rounds": 32}))
    assert rep.qubits_sent == 32
    assert rep.n_delivered == 0  # no entangled pairs


def test_bb84_fails_below_threshold() -> None:
    noisy = line2(link=LinkModel(link_fidelity=0.75, fidelity_std=0.0))
    assert not any(
        compute_report(run_once("bb84", seed=s, topology=noisy)).app_success for s in range(6)
    )


def test_bb84_register_stays_bounded() -> None:
    # The qsend/qrecv rendezvous keeps ~2 qubits alive; a large run must not blow up.
    rep = compute_report(run_once("bb84", seed=0, topology=PERFECT, cfg={"rounds": 512}))
    assert rep.qubits_sent == 512
