"""Policy ordering and metric computation."""

from __future__ import annotations

from qnetbench.api.types import Demand
from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.policies import Edf, FidelityFirst, Fifo, PendingRequest


def _pending(req_id: int, *, fidelity: float, deadline: float | None, t: float) -> PendingRequest:
    return PendingRequest(
        req_id=req_id,
        src="alice",
        dst="bob",
        n=1,
        demand=Demand(min_fidelity=fidelity, deadline=deadline),
        request_time=t,
    )


def test_fifo_orders_by_request_time() -> None:
    reqs = [
        _pending(1, fidelity=0.5, deadline=None, t=2.0),
        _pending(2, fidelity=0.9, deadline=None, t=1.0),
    ]
    assert Fifo().order(reqs, now=3.0) == [2, 1]


def test_fidelity_first_prefers_high_fidelity_demand() -> None:
    reqs = [
        _pending(1, fidelity=0.5, deadline=None, t=1.0),
        _pending(2, fidelity=0.99, deadline=None, t=2.0),
    ]
    assert FidelityFirst().order(reqs, now=3.0) == [2, 1]


def test_edf_prefers_earliest_deadline() -> None:
    reqs = [
        _pending(1, fidelity=0.5, deadline=10.0, t=1.0),
        _pending(2, fidelity=0.5, deadline=5.0, t=2.0),
    ]
    assert Edf().order(reqs, now=3.0) == [2, 1]


def test_policy_ordering_ranks_differ_across_workloads() -> None:
    # The seed of the whole project: the same three requests rank differently
    # under different policies. (Full ranking-inversion over runs is Phase 6.)
    reqs = [
        _pending(1, fidelity=0.99, deadline=100.0, t=1.0),  # high fidelity, loose deadline
        _pending(2, fidelity=0.50, deadline=2.0, t=2.0),  # low fidelity, tight deadline
    ]
    assert FidelityFirst().order(reqs, now=3.0)[0] == 1
    assert Edf().order(reqs, now=3.0)[0] == 2


def test_metrics_are_internally_consistent() -> None:
    rep = compute_report(run_once("distributed_gate", seed=0))
    assert rep.n_requests == rep.n_delivered  # every request delivered in Phase 0
    assert rep.n_delivered > 0
    assert 0.0 <= rep.mean_fidelity <= 1.0
    assert rep.msgs_per_pair > 0  # distributed gate is classically coupled
    assert rep.sim_duration > 0


def test_native_and_policy_modes_both_run() -> None:
    native = compute_report(run_once("qkd", seed=0, arbitration="native"))
    policy = compute_report(run_once("qkd", seed=0, arbitration="policy:edf"))
    assert native.arbitration == "native"
    assert policy.arbitration == "policy:edf"
    assert native.app_utility > 0 and policy.app_utility > 0
    # Single-tenant: no contention, so the arbiter is pass-through and outcomes match.
    assert native.app_utility == policy.app_utility
