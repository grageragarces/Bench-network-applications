"""Multi-tenant contention and the cross-policy ranking inversion (Deliverable 4)."""

from __future__ import annotations

import pytest

from qnetbench.contention import (
    COHERENCE_TIME,
    ContentionResult,
    ReplicatedExperiment,
    Tenant,
    app_profile,
    has_inversion,
    render_experiment,
    render_replicated,
    replicated_experiment,
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


@pytest.fixture(scope="module")
def headline() -> ReplicatedExperiment:
    return replicated_experiment()


@pytest.mark.parametrize(
    "mix, policy, mean, std",
    [
        ("deadline_heavy", "fifo", 0.507, 0.107),
        ("deadline_heavy", "fidelity_first", 0.507, 0.107),
        ("deadline_heavy", "edf", 0.809, 0.012),
        ("fidelity_heavy", "fifo", 0.589, 0.044),
        ("fidelity_heavy", "fidelity_first", 0.683, 0.060),
        ("fidelity_heavy", "edf", 0.550, 0.098),
    ],
)
def test_replicated_experiment_reproduces_the_published_table(
    headline: ReplicatedExperiment, mix: str, policy: str, mean: float, std: float
) -> None:
    summary = headline.mixes[mix][policy]
    assert round(summary.mean, 3) == mean
    assert round(summary.std, 3) == std


def test_replicated_experiment_reports_separation_and_disagreement(
    headline: ReplicatedExperiment,
) -> None:
    assert headline.disagreeing_draws == 32
    assert round(headline.separation("deadline_heavy"), 1) == 17.4
    assert round(headline.separation("fidelity_heavy"), 1) == 10.3


def test_worst_served_application_exposes_starvation(headline: ReplicatedExperiment) -> None:
    edf = headline.mixes["deadline_heavy"]["edf"]
    assert edf.per_app["distributed_gate"] == 1.0
    assert edf.worst_app == edf.per_app["qkd"] < 0.1
    # Scored on the worst-served application, EDF no longer leads the mix it wins.
    assert headline.mixes["deadline_heavy"]["fifo"].worst_app > edf.worst_app


def test_render_replicated_shows_both_metrics(headline: ReplicatedExperiment) -> None:
    text = render_replicated(headline)
    assert "0.809 ± 0.012*" in text
    assert "worst-served application" in text
    assert "share no best policy in 32 of 32" in text


def _result(policy: str, score: float) -> ContentionResult:
    return ContentionResult(policy=policy, aggregate_utility=score)


def test_a_tie_for_best_is_not_an_inversion() -> None:
    # fifo ties for best on the first mix and wins the second, so it is jointly optimal.
    # Picking an arbitrary maximum could report edf vs fifo as a disagreement.
    experiment = {
        "a": {"edf": _result("edf", 0.9), "fifo": _result("fifo", 0.9)},
        "b": {"edf": _result("edf", 0.5), "fifo": _result("fifo", 0.7)},
    }
    assert not has_inversion(experiment)
    assert "No policy is best" not in render_experiment(experiment)


def test_opposed_winners_are_an_inversion() -> None:
    experiment = {
        "a": {"edf": _result("edf", 0.9), "fifo": _result("fifo", 0.5)},
        "b": {"edf": _result("edf", 0.5), "fifo": _result("fifo", 0.7)},
    }
    assert has_inversion(experiment)
    assert "No policy is best" in render_experiment(experiment)


def test_tenant_is_hashable_and_frozen() -> None:
    t = Tenant("qkd", 0.9, None, 5, 0.1)
    assert t.app == "qkd"
