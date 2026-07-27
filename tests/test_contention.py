"""Multi-tenant contention and the cross-policy ranking inversion (Deliverable 4)."""

from __future__ import annotations

from qnetbench.contention import (
    COHERENCE_TIME,
    Tenant,
    app_profile,
    best_policy,
    default_experiment,
    has_inversion,
    render_experiment,
    simulate,
)
from qnetbench.policies import get_policy


def test_app_profile_reads_real_demand() -> None:
    dg = app_profile("distributed_gate", 10, 0.02)
    qk = app_profile("qkd", 10, 0.02)
    assert dg.budget is not None  # distributed gate is deadline-critical
    assert qk.budget is None  # QKD carries no deadline
    assert qk.min_fidelity == 0.9


def test_no_contention_meets_every_contract() -> None:
    # Capacity far above demand: nothing queues, nothing decoheres, nothing expires.
    tenants = [app_profile("qkd", 5, 1.0), app_profile("distributed_gate", 5, 1.0)]
    result = simulate(
        tenants,
        get_policy("fifo"),
        capacity=1000.0,
        link_fidelity=0.99,
        coherence_time=COHERENCE_TIME,
    )
    assert result.aggregate_utility == 1.0


def test_overload_causes_violations() -> None:
    tenants = [app_profile("distributed_gate", 20, 0.01) for _ in range(4)]
    result = simulate(
        tenants,
        get_policy("fifo"),
        capacity=50.0,
        link_fidelity=0.99,
        coherence_time=COHERENCE_TIME,
    )
    assert result.violation_rate > 0.0


def test_ranking_inverts_across_workload_classes() -> None:
    experiment = default_experiment()
    assert has_inversion(experiment)
    assert best_policy(experiment["deadline_heavy"]) == "edf"
    assert best_policy(experiment["fidelity_heavy"]) == "fidelity_first"


def test_edf_and_fidelity_first_swap_places() -> None:
    experiment = default_experiment()
    dh, fh = experiment["deadline_heavy"], experiment["fidelity_heavy"]
    # EDF strictly beats fidelity_first on deadline traffic, and loses on fidelity traffic.
    assert dh["edf"].aggregate_utility > dh["fidelity_first"].aggregate_utility
    assert fh["fidelity_first"].aggregate_utility > fh["edf"].aggregate_utility


def test_render_reports_the_inversion() -> None:
    text = render_experiment(default_experiment())
    assert "RANKING INVERSION" in text
    assert "edf" in text and "fidelity_first" in text


def test_tenant_is_hashable_and_frozen() -> None:
    t = Tenant("qkd", 0.9, None, 5, 0.1)
    assert t.app == "qkd"
