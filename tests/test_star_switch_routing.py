"""Tests for the StarSwitchRouting multi-qubit-per-node multipartite routing benchmark."""

from __future__ import annotations

from qnetbench.apps import StarSwitchRouting, catalog_apps, get_app
from qnetbench.harness import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, default_topology


def test_star_switch_routing_registered_in_catalog() -> None:
    assert "star_switch_routing" in catalog_apps()
    app = get_app("star_switch_routing")
    assert isinstance(app, StarSwitchRouting)
    assert app.roles() == ["hub", "leaf0", "leaf1", "leaf2", "leaf3"]


def test_star_switch_routing_noiseless_unit_utility() -> None:
    topo = default_topology(
        StarSwitchRouting().roles(),
        link=LinkModel(link_fidelity=1.0, fidelity_std=0.0),
    )
    events = run_once(
        "star_switch_routing",
        backend="reference",
        topology=topo,
        cfg={"rounds": 12},
        seed=0,
    )
    report = compute_report(events)
    assert report.app_utility == 1.0
    assert report.app_success is True


def test_star_switch_routing_degrades_smoothly_under_link_noise() -> None:
    def _mean_utility(f_link: float) -> float:
        topo = default_topology(
            StarSwitchRouting().roles(),
            link=LinkModel(link_fidelity=f_link, fidelity_std=0.0),
        )
        events = run_once(
            "star_switch_routing",
            backend="reference",
            topology=topo,
            cfg={"rounds": 20},
            seed=42,
        )
        return compute_report(events).app_utility

    u_perfect = _mean_utility(1.0)
    u_high = _mean_utility(0.98)
    u_low = _mean_utility(0.75)
    assert u_perfect == 1.0
    assert u_low < u_high <= u_perfect
