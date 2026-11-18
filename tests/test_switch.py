"""Tenants on the leaves of a star, served by a switch at its hub."""

from __future__ import annotations

import math

import pytest

from qnetbench.backends.reference.switch import leg_weights, swap
from qnetbench.tenancy import ExecutionModel, TenantSpec, run_tenants
from qnetbench.topology import LinkModel
from qnetbench.trace.events import EntanglementDelivered

LINK = LinkModel(1 / 160, 0.95, 0.0)


def _run(tenants, placement, **kwargs):
    return run_tenants(
        tenants, seed=1, link=LINK, classical_latency=1e-3, placement=placement, **kwargs
    )


def _qkd(name: str, rounds: int = 64) -> TenantSpec:
    return TenantSpec(name, "qkd", {"rounds": rounds})


def _fidelities(run, name: str) -> list[float]:
    return [e.actual_fidelity for e in run.traces[name] if isinstance(e, EntanglementDelivered)]


def _finish(run, name: str) -> float:
    return run.traces[name][-1].t


def test_swapping_two_werner_pairs_gives_the_textbook_fidelity() -> None:
    f1, f2 = 0.95, 0.9
    out = swap(leg_weights(f1, f1, "depolarizing"), leg_weights(f2, f2, "depolarizing"))
    assert out[0] == pytest.approx(f1 * f2 + (1 - f1) * (1 - f2) / 3)
    assert sum(out) == pytest.approx(1.0)


def test_swapping_two_dephased_pairs_stays_dephased() -> None:
    out = swap(leg_weights(0.9, 0.9, "dephasing"), leg_weights(0.8, 0.8, "dephasing"))
    assert out == pytest.approx((0.9 * 0.8 + 0.1 * 0.2, 0.0, 0.9 * 0.2 + 0.1 * 0.8, 0.0))


def test_delivered_pair_is_the_swap_of_two_legs() -> None:
    run = _run([_qkd("a")], {"a": ("L1", "L2")}, model=ExecutionModel(aging="none"))
    expected = 0.95 * 0.95 + 0.05 * 0.05 / 3
    assert all(f == pytest.approx(expected) for f in _fidelities(run, "a"))


def test_a_pair_waiting_at_the_hub_decays() -> None:
    run = _run([_qkd("a")], {"a": ("L1", "L2")}, coherence_time=0.01)
    expected = 0.95 * 0.95 + 0.05 * 0.05 / 3
    assert max(_fidelities(run, "a")) < expected


def test_disjoint_tenants_are_served_in_parallel() -> None:
    alone = _run([_qkd("a")], {"a": ("L1", "L2")})
    disjoint = _run([_qkd("a"), _qkd("b")], {"a": ("L1", "L2"), "b": ("L3", "L4")})
    shared = _run([_qkd("a"), _qkd("b")], {"a": ("L1", "L2"), "b": ("L1", "L3")})
    assert _finish(disjoint, "a") == _finish(alone, "a")
    assert _finish(shared, "a") > _finish(alone, "a")


def test_the_policy_orders_requests_that_share_a_leg() -> None:
    # Two tenants on a leg only alternate, since the leg is free again before its last user asks
    # for more. A third gives the policy a choice.
    tenants = [
        TenantSpec("gate", "distributed_gate", {"reps": 32}),
        _qkd("bg1", 256),
        _qkd("bg2", 256),
    ]
    placement = {"gate": ("L1", "L2"), "bg1": ("L1", "L3"), "bg2": ("L1", "L4")}
    fifo = _run(tenants, placement, arbitration="policy:fifo")
    edf = _run(tenants, placement, arbitration="policy:edf")
    assert _finish(edf, "gate") < _finish(fifo, "gate")


def test_manifest_records_the_placement() -> None:
    run = _run([_qkd("a")], {"a": ("L1", "L2")})
    assert run.manifest()["placement"] == {"a": ["L1", "L2"]}


def test_every_tenant_needs_two_different_leaves() -> None:
    with pytest.raises(ValueError, match="no placement"):
        _run([_qkd("a"), _qkd("b")], {"a": ("L1", "L2")})
    with pytest.raises(ValueError, match="two different leaves"):
        _run([_qkd("a")], {"a": ("L1", "L1")})


def test_only_on_demand_service_is_supported() -> None:
    with pytest.raises(NotImplementedError, match="on_demand"):
        _run([_qkd("a")], {"a": ("L1", "L2")}, model=ExecutionModel(service="ticks"))


def test_one_link_runs_are_unchanged_by_the_new_argument() -> None:
    plain = run_tenants([_qkd("a")], seed=3, link=LINK)
    explicit = run_tenants([_qkd("a")], seed=3, link=LINK, placement=None)
    assert plain.traces == explicit.traces
    assert not math.isnan(_finish(plain, "a"))
