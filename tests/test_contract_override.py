"""Varying a contract and the link without editing the application."""

from __future__ import annotations

from pathlib import Path

import pytest

from qnetbench.contention import app_profile
from qnetbench.harness.cli import main
from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.trace.events import EntanglementDelivered, EntanglementRequested
from qnetbench.trace.io import read_trace


def _requests(events: list) -> list[EntanglementRequested]:
    return [e for e in events if isinstance(e, EntanglementRequested)]


def test_override_reaches_every_request_and_the_trace() -> None:
    events = run_once("qkd", demand_override={"min_fidelity": 0.5, "priority": 3.0})
    requests = _requests(events)
    assert requests
    assert {r.demand.min_fidelity for r in requests} == {0.5}
    assert {r.demand.priority for r in requests} == {3.0}


def test_latency_budget_replaces_the_applications_own_deadline() -> None:
    assert any(r.demand.deadline is not None for r in _requests(run_once("distributed_gate")))
    requests = _requests(run_once("distributed_gate", demand_override={"latency_budget": 0.2}))
    assert {r.demand.latency_budget for r in requests} == {0.2}
    assert {r.demand.deadline for r in requests} == {None}


def test_override_changes_what_is_reported_not_what_the_protocol_does() -> None:
    plain = compute_report(run_once("qkd", seed=2))
    strict = compute_report(run_once("qkd", seed=2, demand_override={"min_fidelity": 0.999}))
    assert strict.app_utility == plain.app_utility
    assert strict.violation_rate > plain.violation_rate


def test_override_leaves_an_application_without_entanglement_requests_alone() -> None:
    plain = run_once("bb84", seed=1)
    overridden = run_once("bb84", seed=1, demand_override={"min_fidelity": 0.5})
    assert not _requests(plain)
    assert [e.model_dump() for e in overridden] == [e.model_dump() for e in plain]


@pytest.mark.parametrize(
    "override, message",
    [
        ({"purpose": "measure"}, "cannot override"),
        ({"deadline": 1.0}, "cannot override"),
        ({"min_fidelity": 2.0}, "less than or equal"),
    ],
)
def test_invalid_overrides_are_rejected_before_the_run(override: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        run_once("qkd", demand_override=override)


def test_tenant_built_with_an_override_carries_it() -> None:
    override = {"min_fidelity": 0.7, "latency_budget": 0.1}
    tenant = app_profile("distributed_gate", 10, 0.03, demand_override=override)
    assert tenant.min_fidelity == 0.7
    assert tenant.budget == 0.1


def test_cli_applies_link_and_contract_flags(tmp_path: Path) -> None:
    out = tmp_path / "trace.jsonl"
    argv = [
        "run", "qkd", "--out", str(out),
        "--link-fidelity", "0.99", "--fidelity-std", "0",
        "--min-fidelity", "0.85", "--latency-budget", "0.5",
    ]  # fmt: skip
    assert main(argv) == 0
    events = list(read_trace(out))
    assert {r.demand.min_fidelity for r in _requests(events)} == {0.85}
    assert {r.demand.latency_budget for r in _requests(events)} == {0.5}
    delivered = [e for e in events if isinstance(e, EntanglementDelivered)]
    assert {e.actual_fidelity for e in delivered} == {0.99}


def test_cli_rejects_an_out_of_range_contract(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "qkd", "--min-fidelity", "2"]) == 2
    assert "less than or equal" in capsys.readouterr().err
