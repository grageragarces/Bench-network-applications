"""The shape of a link's error at a given fidelity (`LinkModel.noise`)."""

from __future__ import annotations

import statistics

import pytest

from qnetbench.apps import get_app
from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, default_topology, line2
from qnetbench.trace.events import AppOutcomeEvent

F = 0.85


def _qber(noise: str, seeds: int = 6) -> float:
    values = []
    for seed in range(seeds):
        events = run_once(
            "qkd",
            seed=seed,
            topology=line2(link=LinkModel(1e-3, F, 0.0, noise)),
            cfg={"rounds": 512},
        )
        outcome = next(e for e in events if isinstance(e, AppOutcomeEvent))
        values.append(float(outcome.payload["qber"]))
    return statistics.fmean(values)


def test_default_noise_is_werner_and_unchanged() -> None:
    plain = line2(link=LinkModel(1e-3, F, 0.01))
    explicit = line2(link=LinkModel(1e-3, F, 0.01, "depolarizing"))
    assert run_once("teleportation", seed=2, topology=plain) == run_once(
        "teleportation", seed=2, topology=explicit
    )


def test_werner_qber_is_two_thirds_of_the_infidelity() -> None:
    assert _qber("depolarizing") == pytest.approx(2 * (1 - F) / 3, abs=0.02)


@pytest.mark.parametrize("noise", ["dephasing", "bit_flip"])
def test_one_sided_noise_errs_in_one_basis_only(noise: str) -> None:
    # BBM92 measures in Z and X equally often, and these errors flip only one of the two.
    assert _qber(noise) == pytest.approx((1 - F) / 2, abs=0.02)


def test_swapping_dephased_links_beats_werner_links_at_equal_fidelity() -> None:
    def utility(noise: str) -> float:
        roles = get_app("entanglement_swap").roles()
        topo = default_topology(roles, link=LinkModel(1e-3, F, 0.0, noise))
        return statistics.fmean(
            compute_report(
                run_once("entanglement_swap", seed=s, topology=topo, cfg={"rounds": 256})
            ).app_utility
            for s in range(4)
        )

    assert utility("dephasing") > utility("depolarizing") + 0.02
