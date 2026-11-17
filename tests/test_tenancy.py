"""Concurrent execution: several applications on one shared link."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from qnetbench.api.types import Demand
from qnetbench.apps import available_apps, get_app
from qnetbench.backends.reference.engine import ApplicationFailure, Engine
from qnetbench.backends.reference.link import LinkRequest, LinkServer
from qnetbench.backends.reference.qstate import Register
from qnetbench.contention import arrival_times, default_mixes, simulate
from qnetbench.harness.runner import run_once
from qnetbench.policies import get_policy
from qnetbench.tenancy import (
    AS_QUEUE_MODEL,
    ExecutionModel,
    TenantSpec,
    application_utility,
    contract_satisfaction,
    queue_model_on_link,
    run_tenants,
)
from qnetbench.topology import LinkModel
from qnetbench.trace.events import (
    ContractViolation,
    EntanglementDelivered,
    EntanglementRequested,
)
from qnetbench.trace.io import read_trace

TWO_ROLE = [name for name in available_apps() if len(get_app(name).roles()) == 2]
MULTI_PAIR = {"distillation", "distilled_gate"}  # request more than one pair at a time
PLAIN = ExecutionModel(arrivals="closed_loop", aging="none", service_unit="request")
LINK = LinkModel(attempt_latency=1.0 / 160, link_fidelity=0.99, fidelity_std=0.0)


def _tenants(apps: dict[str, dict[str, object]]) -> list[TenantSpec]:
    return [TenantSpec(f"t{i}", app, cfg) for i, (app, cfg) in enumerate(apps.items())]


# --- the modelling decisions ---------------------------------------------------------


def test_the_documented_defaults_hold():
    model = ExecutionModel()
    assert model.arrivals == "paced"
    assert model.aging == "held_qubits"
    assert model.memory_noise == "dephasing"
    assert model.missed_deadline == "serve_late"
    assert model.service_unit == "pair"


@pytest.mark.parametrize(
    "field,value",
    [
        ("arrivals", "sessions"),
        ("aging", "magic"),
        ("memory_noise", "amplitude_damping"),
        ("missed_deadline", "ignore"),
        ("service_unit", "batch"),
        ("service", "instant"),
        ("storage", 0),
        ("stored_pair", "random"),
    ],
)
def test_an_unknown_choice_is_refused(field, value):
    with pytest.raises(ValueError, match=field):
        ExecutionModel(**{field: value})


def test_multipartite_applications_are_out_of_scope_and_say_so():
    with pytest.raises(NotImplementedError, match="decision 6"):
        run_tenants([TenantSpec("t", "conference_key")])


def test_tenant_names_must_be_unique():
    with pytest.raises(ValueError, match="unique"):
        run_tenants([TenantSpec("t", "qkd"), TenantSpec("t", "chsh")])


# --- one tenant is run_once ----------------------------------------------------------


@pytest.mark.parametrize("app", TWO_ROLE)
def test_one_tenant_reproduces_run_once(app):
    expected = run_once(app, seed=3)
    assert run_tenants([TenantSpec("only", app)], seed=3, model=PLAIN).traces["only"] == expected


@pytest.mark.parametrize("app", [a for a in TWO_ROLE if a not in MULTI_PAIR])
def test_serving_pair_by_pair_changes_nothing_for_single_pair_requests(app):
    model = ExecutionModel(arrivals="closed_loop", aging="none", service_unit="pair")
    expected = run_once(app, seed=4)
    assert run_tenants([TenantSpec("only", app)], seed=4, model=model).traces["only"] == expected


def test_memory_with_no_decay_changes_nothing():
    model = ExecutionModel(arrivals="closed_loop", service_unit="request")
    run = run_tenants([TenantSpec("only", "bqc")], seed=5, model=model)
    assert run.traces["only"] == run_once("bqc", seed=5)


# --- the server against the queue model ----------------------------------------------


@pytest.mark.parametrize("seed", [0, 1, 2])
@pytest.mark.parametrize("mix", ["deadline_heavy", "fidelity_heavy"])
@pytest.mark.parametrize("policy", ["fifo", "fidelity_first", "edf"])
def test_the_server_computes_the_queue_model_exactly(seed, mix, policy):
    tenants = default_mixes(100, seed=seed)[mix]
    params = {"capacity": 160.0, "link_fidelity": 0.99, "coherence_time": 0.25}
    expected = simulate(tenants, get_policy(policy), **params)
    actual = queue_model_on_link(tenants, get_policy(policy), **params)
    assert actual.aggregate_utility == expected.aggregate_utility
    assert actual.per_app == expected.per_app


_ONE_REQUEST = {"distributed_gate": "reps", "qkd": "rounds", "bqc": "depth", "chsh": "rounds"}


@pytest.mark.parametrize("seed", [0, 1])
@pytest.mark.parametrize("mix", ["deadline_heavy", "fidelity_heavy"])
@pytest.mark.parametrize("policy", ["fifo", "fidelity_first", "edf"])
def test_real_applications_give_the_queue_models_answer_under_its_assumptions(seed, mix, policy):
    # The strongest check on the whole stack. Each request is its own running application, so
    # arrivals stay open loop as the model assumes, and the score must match to the last bit.
    tenants = default_mixes(40, seed=seed)[mix]
    expected = simulate(
        tenants, get_policy(policy), capacity=160.0, link_fidelity=0.99, coherence_time=0.25
    )
    specs = [
        TenantSpec(f"{i}-{k}", t.app, {_ONE_REQUEST[t.app]: 1}, arrivals=(when,))
        for i, t in enumerate(tenants)
        for k, when in enumerate(arrival_times(t))
    ]
    run = run_tenants(
        specs,
        seed=seed,
        arbitration=f"policy:{policy}",
        link=LINK,
        classical_latency=1e-3,
        coherence_time=0.25,
        model=AS_QUEUE_MODEL,
    )
    met = [contract_satisfaction(run.traces[s.name]) for s in specs]
    assert sum(met) / len(met) == pytest.approx(expected.aggregate_utility, abs=1e-12)
    for app, value in expected.per_app.items():
        scores = [m for s, m in zip(specs, met, strict=True) if s.app == app]
        assert sum(scores) / len(scores) == pytest.approx(value, abs=1e-12)


# --- the server's behaviour ----------------------------------------------------------


def _request(
    arrival, *, n=1, deadline=None, log=None, name="r", stored_log=None, engine_now=lambda: 0.0
):
    log = log if log is not None else []

    def served(_latency, _fidelities, _waited, last, stored):
        log.append((name, "served", last))
        if stored_log is not None:
            stored_log.append((name, round(engine_now(), 6), round(stored, 6)))

    def dropped(pairs):
        log.append((name, "dropped", pairs))

    return LinkRequest(
        src="a",
        dst="b",
        remaining=n,
        demand=Demand(deadline=deadline),
        arrival=arrival,
        on_served=served,
        on_dropped=dropped,
    )


def _supply(latency=1.0):
    return lambda _src, _dst, pairs: (latency * pairs, [0.9] * pairs)


def test_the_policy_decides_who_is_served_next():
    engine = Engine()
    log = []
    server = LinkServer(engine, _supply(), policy=get_policy("edf"))
    engine.call_at(0.0, lambda: server.submit(_request(0.0, deadline=9.0, log=log, name="first")))
    engine.call_at(0.1, lambda: server.submit(_request(0.1, deadline=8.0, log=log, name="late")))
    engine.call_at(0.2, lambda: server.submit(_request(0.2, deadline=2.0, log=log, name="urgent")))
    engine.run()
    assert [entry[0] for entry in log] == ["first", "urgent", "late"]


def test_native_serves_first_come_first_served():
    engine = Engine()
    log = []
    server = LinkServer(engine, _supply())
    engine.call_at(0.0, lambda: server.submit(_request(0.0, deadline=9.0, log=log, name="a")))
    engine.call_at(0.1, lambda: server.submit(_request(0.1, deadline=8.0, log=log, name="b")))
    engine.call_at(0.2, lambda: server.submit(_request(0.2, deadline=2.0, log=log, name="c")))
    engine.run()
    assert [entry[0] for entry in log] == ["a", "b", "c"]


@pytest.mark.parametrize(
    "unit,expected",
    [("pair", ["long", "urgent", "long", "long"]), ("request", ["long", "urgent"])],
)
def test_service_unit_decides_when_the_policy_chooses_again(unit, expected):
    engine = Engine()
    log = []
    server = LinkServer(engine, _supply(), policy=get_policy("edf"), service_unit=unit)
    long = _request(0.0, n=3, deadline=9.0, log=log, name="long")
    engine.call_at(0.0, lambda: server.submit(long))
    engine.call_at(0.1, lambda: server.submit(_request(0.1, deadline=2.0, log=log, name="urgent")))
    engine.run()
    assert [entry[0] for entry in log] == expected
    assert [entry[2] for entry in log if entry[0] == "long"][-1] is True


def test_serve_late_serves_a_request_past_its_deadline():
    engine = Engine()
    log = []
    server = LinkServer(engine, _supply(5.0))
    engine.call_at(0.0, lambda: server.submit(_request(0.0, log=log, name="a")))
    engine.call_at(0.1, lambda: server.submit(_request(0.1, deadline=1.0, log=log, name="b")))
    engine.run()
    assert log == [("a", "served", True), ("b", "served", True)]


def test_drop_uses_no_link_capacity():
    engine = Engine()
    log = []
    drawn = []

    def supply(_src, _dst, pairs):
        drawn.append(pairs)
        return 5.0, [0.9] * pairs

    server = LinkServer(engine, supply, missed_deadline="drop")
    engine.call_at(0.0, lambda: server.submit(_request(0.0, log=log, name="a")))
    engine.call_at(0.1, lambda: server.submit(_request(0.1, n=2, deadline=1.0, log=log, name="b")))
    engine.run()
    assert log == [("a", "served", True), ("b", "dropped", 2)]
    assert drawn == [1]


# --- schedulers that keep state ------------------------------------------------------


class _Recording:
    """Serves the tenant it has delivered to least, and records what it was told."""

    name = "recording_for_test"

    def __init__(self):
        self.resets = 0
        self.seen = []
        self.counts = {}

    def reset(self):
        self.resets += 1
        self.seen = []
        self.counts = {}

    def on_delivery(self, request, fidelity, at):
        self.seen.append((request.tenant, fidelity, at))
        self.counts[request.tenant] = self.counts.get(request.tenant, 0) + 1

    def order(self, pending, now):
        def key(p):
            return (self.counts.get(p.tenant, 0), p.request_time, p.req_id)

        return [p.req_id for p in sorted(pending, key=key)]


@pytest.fixture
def recording():
    from qnetbench.policies.builtin import _REGISTRY, register_policy

    policy = _Recording()
    register_policy(policy)
    yield policy
    del _REGISTRY[policy.name]


@pytest.mark.parametrize("service", ["on_demand", "ticks", "free_running"])
def test_a_policy_is_told_about_each_delivery(recording, service):
    tenants = _tenants({"qkd": {"rounds": 10}, "chsh": {"rounds": 6}})
    model = ExecutionModel(arrivals="closed_loop", service=service)
    arbitration = "policy:recording_for_test"
    run = run_tenants(tenants, seed=0, arbitration=arbitration, link=LINK, model=model)
    assert recording.counts == {"t0": 10, "t1": 6}
    assert {fidelity for _, fidelity, _ in recording.seen} == {0.99}
    for name in ("t0", "t1"):
        told = [at for tenant, _, at in recording.seen if tenant == name]
        delivered = [e.t for e in run.traces[name] if isinstance(e, EntanglementDelivered)]
        assert told == pytest.approx(delivered)


def test_a_stateful_policy_starts_each_run_clean(recording):
    tenants = _tenants({"qkd": {"rounds": 10}, "chsh": {"rounds": 10}})
    first = run_tenants(tenants, seed=3, arbitration="policy:recording_for_test", link=LINK)
    second = run_tenants(tenants, seed=3, arbitration="policy:recording_for_test", link=LINK)
    assert recording.resets == 2
    assert first.traces == second.traces


def test_a_policy_with_no_hooks_needs_none():
    tenants = _tenants({"qkd": {"rounds": 6}, "chsh": {"rounds": 6}})
    run_tenants(tenants, seed=0, arbitration="policy:fifo", link=LINK)


# --- a free-running link -------------------------------------------------------------


def test_a_free_running_link_generates_regardless_and_keeps_the_newest_pair():
    engine = Engine()
    stored = []
    server = LinkServer(engine, _supply(1.0), storage=1)
    server.start()
    request = _request(2.5, stored_log=stored, engine_now=lambda: engine.now, name="r")
    engine.call_at(2.5, lambda: server.submit(request))
    engine.run()
    assert stored == [("r", 2.5, 0.5)]  # the pair made at 2.0, not the one made at 1.0


def test_more_storage_lets_several_requests_be_served_at_once_newest_first():
    engine = Engine()
    stored = []
    server = LinkServer(engine, _supply(1.0), storage=3)
    server.start()
    now = lambda: engine.now  # noqa: E731
    a = _request(4.5, stored_log=stored, engine_now=now, name="a")
    b = _request(4.5, stored_log=stored, engine_now=now, name="b")
    engine.call_at(4.5, lambda: server.submit(a))
    engine.call_at(4.5, lambda: server.submit(b))
    engine.run()
    assert stored == [("a", 4.5, 0.5), ("b", 4.5, 1.5)]


def test_a_link_can_hand_over_its_oldest_stored_pair_instead():
    engine = Engine()
    stored = []
    server = LinkServer(engine, _supply(1.0), storage=3, stored_pair="oldest")
    server.start()
    request = _request(4.5, stored_log=stored, engine_now=lambda: engine.now, name="r")
    engine.call_at(4.5, lambda: server.submit(request))
    engine.run()
    assert stored == [("r", 4.5, 2.5)]  # pairs made at 2, 3 and 4 are held, and 2 goes first


def test_under_overload_a_pair_goes_straight_to_a_waiting_request_fresh():
    engine = Engine()
    stored = []
    server = LinkServer(engine, _supply(1.0), storage=5)
    server.start()
    now = lambda: engine.now  # noqa: E731
    for name in "abc":
        request = _request(0.0, stored_log=stored, engine_now=now, name=name)
        engine.call_at(0.0, lambda r=request: server.submit(r))
    engine.run()
    assert stored == [("a", 1.0, 0.0), ("b", 2.0, 0.0), ("c", 3.0, 0.0)]


def test_free_running_serves_pair_by_pair_only():
    with pytest.raises(ValueError, match="one pair at a time"):
        ExecutionModel(service="free_running", service_unit="request")


FREE = ExecutionModel(arrivals="closed_loop", service="free_running", storage=1)


def test_free_running_tenants_finish_and_stored_pairs_show_their_age():
    # Sparse demand on a fast link: the pair each request gets has been sitting in storage.
    fast = LinkModel(attempt_latency=1e-3, link_fidelity=0.99, fidelity_std=0.0)
    schedule = tuple(0.1 * (k + 1) for k in range(10))
    tenant = TenantSpec("t", "qkd", {"rounds": 10}, arrivals=schedule)
    model = ExecutionModel(service="free_running", storage=1)
    run = run_tenants([tenant], seed=0, link=fast, coherence_time=0.25, model=model)
    delivered = [e for e in run.traces["t"] if isinstance(e, EntanglementDelivered)]
    assert len(delivered) == 10
    assert all(e.pair_age > 0.0 for e in delivered)
    assert all(e.actual_fidelity < 0.99 for e in delivered)


def test_free_running_under_overload_delivers_fresh_pairs():
    slow = LinkModel(attempt_latency=0.01, link_fidelity=0.99, fidelity_std=0.0)
    tenants = [TenantSpec(f"t{i}", "qkd", {"rounds": 12}) for i in range(4)]
    run = run_tenants(tenants, seed=0, link=slow, coherence_time=0.25, model=FREE)
    ages = [
        e.pair_age
        for trace in run.traces.values()
        for e in trace
        if isinstance(e, EntanglementDelivered)
    ]
    assert len(ages) == 48
    assert sum(age == 0.0 for age in ages) > 40


def test_free_running_runs_are_deterministic():
    tenants = _tenants({"qkd": {"rounds": 20}, "chsh": {"rounds": 20}})
    a = run_tenants(tenants, seed=7, arbitration="policy:edf", link=LINK, model=FREE)
    b = run_tenants(tenants, seed=7, arbitration="policy:edf", link=LINK, model=FREE)
    assert a.traces == b.traces


def test_a_deadlock_on_a_free_running_link_is_reported_rather_than_hanging():
    class Stuck:
        name = "stuck_for_test"

        def roles(self):
            return ["alice", "bob"]

        def run(self, host, role, cfg):
            host.classical_socket("bob" if role == "alice" else "alice").recv()

    from qnetbench.apps import _CATALOG

    _CATALOG["stuck_for_test"] = Stuck()
    try:
        with pytest.raises(RuntimeError, match="did not complete"):
            run_tenants([TenantSpec("t", "stuck_for_test")], link=LINK, model=FREE)
    finally:
        del _CATALOG["stuck_for_test"]


# --- several tenants -----------------------------------------------------------------


def test_runs_are_deterministic():
    tenants = _tenants({"qkd": {"rounds": 20}, "chsh": {"rounds": 20}, "bqc": {"depth": 10}})
    for arbitration in ("native", "policy:edf"):
        a = run_tenants(tenants, seed=7, arbitration=arbitration, link=LINK, coherence_time=0.25)
        b = run_tenants(tenants, seed=7, arbitration=arbitration, link=LINK, coherence_time=0.25)
        assert a.traces == b.traces


def test_tenants_of_one_application_keep_to_themselves():
    tenants = [TenantSpec("a", "qkd", {"rounds": 12}), TenantSpec("b", "qkd", {"rounds": 30})]
    run = run_tenants(tenants, seed=1, link=LINK)
    assert sum(isinstance(e, EntanglementRequested) for e in run.traces["a"]) == 12
    assert sum(isinstance(e, EntanglementRequested) for e in run.traces["b"]) == 30


def test_the_link_serves_one_pair_at_a_time_across_tenants():
    tenants = _tenants({"qkd": {"rounds": 30}, "chsh": {"rounds": 30}})
    run = run_tenants(tenants, seed=2, link=LINK, model=AS_QUEUE_MODEL, coherence_time=0.25)
    times = sorted(
        e.t for trace in run.traces.values() for e in trace if isinstance(e, EntanglementDelivered)
    )
    assert len(times) == 60
    assert min(b - a for a, b in zip(times, times[1:], strict=False)) >= LINK.attempt_latency * 0.99


def test_contention_makes_a_tenant_wait():
    alone = run_tenants([TenantSpec("a", "qkd", {"rounds": 40})], seed=2, link=LINK)
    shared = run_tenants(
        _tenants({"qkd": {"rounds": 40}, "chsh": {"rounds": 40}, "bqc": {"depth": 40}}),
        seed=2,
        link=LINK,
    )
    assert shared.traces["t0"][-1].t > 1.5 * alone.traces["a"][-1].t


@pytest.mark.parametrize("policy", ["native", "policy:fifo", "policy:fidelity_first", "policy:edf"])
@pytest.mark.parametrize("seed", range(4))
def test_mixes_finish_without_deadlock(policy, seed):
    tenants = _tenants(
        {
            "distributed_gate": {"reps": 10},
            "qkd": {"rounds": 10},
            "bqc": {"depth": 10},
            "chsh": {"rounds": 10},
            "distillation": {"rounds": 5, "control_rounds": 5},
        }
    )
    run = run_tenants(tenants, seed=seed, arbitration=policy, link=LINK, coherence_time=0.25)
    assert set(run.traces) == {t.name for t in tenants}


def test_every_two_role_application_can_share_the_link():
    tenants = [TenantSpec(name, name) for name in TWO_ROLE]
    run = run_tenants(tenants, seed=0, arbitration="policy:edf", link=LINK, coherence_time=0.25)
    assert set(run.traces) == set(TWO_ROLE)


def test_a_crash_in_one_tenant_is_reported_as_itself():
    class Broken:
        name = "broken_for_test"

        def roles(self):
            return ["alice", "bob"]

        def run(self, host, role, cfg):
            raise ValueError("boom")

    from qnetbench.apps import _CATALOG

    _CATALOG["broken_for_test"] = Broken()
    try:
        with pytest.raises(ApplicationFailure, match="t1/broken_for_test:alice raised ValueError"):
            run_tenants([TenantSpec("t0", "qkd"), TenantSpec("t1", "broken_for_test")])
    finally:
        del _CATALOG["broken_for_test"]


def test_traces_are_written_one_per_tenant_with_a_manifest(tmp_path):
    tenants = _tenants({"qkd": {"rounds": 8}, "chsh": {"rounds": 8}})
    run = run_tenants(tenants, seed=1, arbitration="policy:fifo", link=LINK, coherence_time=0.25)
    run.write(tmp_path)
    for tenant in tenants:
        assert list(read_trace(tmp_path / f"{tenant.name}.jsonl")) == run.traces[tenant.name]
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["arbitration"] == "policy:fifo"
    assert manifest["model"]["aging"] == "held_qubits"
    assert [t["app"] for t in manifest["tenants"]] == ["qkd", "chsh"]


# --- pacing --------------------------------------------------------------------------


def test_a_paced_request_goes_out_on_schedule():
    schedule = tuple(0.5 + 0.25 * k for k in range(6))
    tenant = TenantSpec("t", "qkd", {"rounds": 6}, arrivals=schedule)
    run = run_tenants([tenant], seed=0, link=LINK)
    requested = [e.t for e in run.traces["t"] if isinstance(e, EntanglementRequested)]
    assert requested == pytest.approx(schedule)


def test_closed_loop_ignores_the_schedule():
    tenant = TenantSpec("t", "qkd", {"rounds": 6}, arrivals=(50.0,) * 6)
    model = ExecutionModel(arrivals="closed_loop")
    run = run_tenants([tenant], seed=0, link=LINK, model=model)
    assert run.traces["t"][-1].t < 50.0


def test_a_deadline_runs_from_when_the_paced_request_goes_out():
    tenant = TenantSpec("t", "distributed_gate", {"reps": 2}, arrivals=(1.0, 2.0))
    run = run_tenants([tenant], seed=0, link=LINK)
    requests = [e for e in run.traces["t"] if isinstance(e, EntanglementRequested)]
    assert [e.demand.deadline - e.t for e in requests] == pytest.approx([0.05, 0.05])
    assert not [
        e
        for e in run.traces["t"]
        if isinstance(e, ContractViolation) and e.violation == "deadline"
    ]


# --- what a missed deadline does to a running application ----------------------------


def _overloaded():
    return [TenantSpec(f"t{i}", "distributed_gate", {"reps": 12}) for i in range(8)]


def test_serving_late_records_a_violation_and_delivers_the_real_pair():
    slow = LinkModel(attempt_latency=0.02, link_fidelity=0.99, fidelity_std=0.0)
    run = run_tenants(_overloaded(), seed=0, link=slow, classical_latency=1e-3)
    for trace in run.traces.values():
        fidelities = {e.actual_fidelity for e in trace if isinstance(e, EntanglementDelivered)}
        assert fidelities == {0.99}
    assert any(
        isinstance(e, ContractViolation) and e.violation == "deadline"
        for trace in run.traces.values()
        for e in trace
    )


def test_dropping_hands_the_application_a_useless_pair_and_it_finishes():
    slow = LinkModel(attempt_latency=0.02, link_fidelity=0.99, fidelity_std=0.0)
    model = ExecutionModel(missed_deadline="drop")
    run = run_tenants(_overloaded(), seed=0, link=slow, classical_latency=1e-3, model=model)
    delivered = [
        e.actual_fidelity
        for trace in run.traces.values()
        for e in trace
        if isinstance(e, EntanglementDelivered)
    ]
    assert 0.25 in delivered and 0.99 in delivered
    assert len(delivered) == 8 * 12


def test_queue_wait_ages_the_pair_and_records_its_age():
    model = ExecutionModel(aging="queue_wait", service="ticks")
    tenants = _tenants({"qkd": {"rounds": 20}, "chsh": {"rounds": 20}})
    run = run_tenants(tenants, seed=0, link=LINK, model=model, coherence_time=0.25)
    delivered = [e for e in run.traces["t1"] if isinstance(e, EntanglementDelivered)]
    assert any(e.pair_age > 0.0 and e.actual_fidelity < 0.99 for e in delivered)


def test_held_qubits_leaves_a_new_pair_fresh():
    tenants = _tenants({"qkd": {"rounds": 20}, "chsh": {"rounds": 20}})
    run = run_tenants(tenants, seed=0, link=LINK, coherence_time=0.25)
    for trace in run.traces.values():
        for event in trace:
            if isinstance(event, EntanglementDelivered):
                assert event.pair_age == 0.0
                assert event.actual_fidelity == 0.99


def test_scoring_helpers():
    run = run_tenants([TenantSpec("t", "qkd", {"rounds": 40})], seed=0, link=LINK)
    assert contract_satisfaction(run.traces["t"]) == 1.0
    assert 0.0 < application_utility(run.traces["t"]) <= 1.0


def test_schedule_comes_from_the_queue_model():
    tenant = default_mixes(5, seed=0)["fidelity_heavy"][0]
    times = arrival_times(tenant)
    assert len(times) == 5
    assert times[0] == tenant.phase
    assert times == sorted(times)


# --- memory --------------------------------------------------------------------------


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _held_register(noise, seed):
    clock = _Clock()
    register = Register(np.random.default_rng(seed))
    register.enable_memory(clock, 1.0, noise, np.random.default_rng(seed + 10_000))
    return register, clock


def _hold_and_measure(noise, prepare_plus, basis, held, shots=4000):
    zeros = 0
    for shot in range(shots):
        register, clock = _held_register(noise, shot)
        qid = register.alloc()
        register.stamp(qid, 0.0, "a")
        if prepare_plus:
            from qnetbench.backends.reference.qstate import _H

            register.apply_1q(qid, _H)
        clock.t = held
        register.settle(qid)
        zeros += register.measure(qid, basis) == 0
    return zeros / shots


@pytest.mark.parametrize("held", [0.25, 1.0])
def test_dephasing_matches_the_closed_form_on_a_superposition(held):
    measured = _hold_and_measure("dephasing", True, "X", held)
    assert measured == pytest.approx((1 + math.exp(-held)) / 2, abs=0.03)


def test_dephasing_cannot_touch_a_computational_basis_state():
    assert _hold_and_measure("dephasing", False, "Z", 1.0) == 1.0


def test_depolarizing_reaches_a_computational_basis_state():
    measured = _hold_and_measure("depolarizing", False, "Z", 1.0)
    assert measured == pytest.approx((1 + math.exp(-1.0)) / 2, abs=0.03)


def test_decay_composes_over_intervals():
    # Settling twice must behave like settling once over the whole time.
    zeros = 0
    shots = 4000
    for shot in range(shots):
        register, clock = _held_register("dephasing", shot)
        qid = register.alloc()
        register.stamp(qid, 0.0, "a")
        from qnetbench.backends.reference.qstate import _H

        register.apply_1q(qid, _H)
        clock.t = 0.4
        register.settle(qid)
        clock.t = 1.0
        register.settle(qid)
        zeros += register.measure(qid, "X") == 0
    assert zeros / shots == pytest.approx((1 + math.exp(-1.0)) / 2, abs=0.03)


def test_paused_time_is_not_charged_and_only_to_that_node():
    register, clock = _held_register("dephasing", 0)
    a, b = register.alloc(), register.alloc()
    register.stamp(a, 0.0, "alice")
    register.stamp(b, 0.0, "bob")
    register.pause("alice", 1.0)
    memory = register._memory
    assert memory.last[a] == 1.0
    assert memory.last[b] == 0.0
    clock.t = 0.5
    register.settle(a)  # still inside the pause, so nothing has accrued
    assert memory.last[a] == 1.0


def test_memory_noise_does_not_move_the_measurement_stream():
    # Noise draws come from their own stream, so turning memory on leaves the register's
    # generator exactly where it was, whether or not the noise fires.
    clock = _Clock()
    register = Register(np.random.default_rng(1))
    memory_rng = np.random.default_rng(2)
    register.enable_memory(clock, 0.1, "depolarizing", memory_rng)
    qid = register.alloc()
    register.stamp(qid, 0.0, "a")
    before = register._rng.bit_generator.state
    memory_before = memory_rng.bit_generator.state
    clock.t = 1.0
    register.settle(qid)
    assert register._rng.bit_generator.state == before
    assert memory_rng.bit_generator.state != memory_before


def test_memory_is_off_unless_asked_for():
    register = Register(np.random.default_rng(1))
    qid = register.alloc()
    register.stamp(qid, 0.0, "a")
    state = register._state.copy()
    register.settle(qid)
    register.pause("a", 1.0)
    assert np.array_equal(register._state, state)


@pytest.mark.parametrize("noise", ["dephasing", "depolarizing"])
@pytest.mark.parametrize("fidelity", [0.99, 0.8])
def test_a_stored_pair_matches_the_fidelity_the_trace_reports(noise, fidelity):
    # Hold both halves, then read the singlet fraction from Z, X and Y agreement.
    age = 0.3
    shots = 6000
    agree = {"Z": 0, "X": 0, "Y": 0}
    for shot in range(shots):
        basis = "ZXY"[shot % 3]
        register, clock = _held_register(noise, shot)
        a, b = register.make_bell_pair(fidelity)
        register.stamp(a, 0.0, "alice")
        register.stamp(b, 0.0, "bob")
        clock.t = age
        register.settle(a)
        register.settle(b)
        agree[basis] += register.measure(a, basis) == register.measure(b, basis)
    rate = {k: v / (shots / 3) for k, v in agree.items()}
    # For Phi+: Z and X agree, Y anticorrelates, so F = (E_Z + E_X - E_Y + 1) / 4.
    correlation = {k: 2 * v - 1 for k, v in rate.items()}
    measured = (correlation["Z"] + correlation["X"] - correlation["Y"] + 1) / 4
    register, _ = _held_register(noise, 0)
    assert measured == pytest.approx(register.aged_fidelity(fidelity, age), abs=0.02)

