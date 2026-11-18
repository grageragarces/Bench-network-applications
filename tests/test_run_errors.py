"""A crashed application role must be reported as a crash, not as a deadlock."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from qnetbench.api import AppOutcome, Demand, Host, Role
from qnetbench.apps import _CATALOG, register_app
from qnetbench.backends.reference.engine import ApplicationFailure
from qnetbench.harness.cli import main
from qnetbench.harness.runner import run_once
from qnetbench.topology import LinkModel, Topology


class _Raises:
    name = "raises_on_alice"

    def roles(self) -> list[Role]:
        return ["alice", "bob"]

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        if role == "alice":
            raise ZeroDivisionError("the bug in the application")
        host.epr_socket("alice").request(1, Demand())  # parked forever: alice has died
        return AppOutcome(role=role, success=True, utility=1.0)


class _BadOutcome:
    """The mistake a newcomer is most likely to make: `AppOutcome` without `role=`."""

    name = "bad_outcome"

    def roles(self) -> list[Role]:
        return ["alice", "bob"]

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        return AppOutcome(success=True, utility=1.0)  # type: ignore[call-arg]


class _Deadlocks:
    name = "real_deadlock"

    def roles(self) -> list[Role]:
        return ["alice", "bob"]

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        peer = "bob" if role == "alice" else "alice"
        host.classical_socket(peer).recv()  # both sides wait, neither sends
        return AppOutcome(role=role, success=True, utility=1.0)


@pytest.fixture
def registered() -> Iterator[None]:
    names = [register_app(app()) for app in (_Raises, _BadOutcome, _Deadlocks)]
    yield
    for name in names:
        del _CATALOG[name]


@pytest.mark.usefixtures("registered")
def test_exception_in_a_role_is_reported_with_its_cause() -> None:
    with pytest.raises(ApplicationFailure, match="raises_on_alice:alice raised ZeroDiv") as info:
        run_once("raises_on_alice")
    assert isinstance(info.value.__cause__, ZeroDivisionError)


@pytest.mark.usefixtures("registered")
def test_invalid_outcome_is_not_reported_as_a_deadlock() -> None:
    with pytest.raises(ApplicationFailure, match="ValidationError"):
        run_once("bad_outcome")


@pytest.mark.usefixtures("registered")
def test_a_real_deadlock_is_still_reported_as_one() -> None:
    with pytest.raises(RuntimeError, match="did not complete") as info:
        run_once("real_deadlock")
    assert not isinstance(info.value, ApplicationFailure)


def test_missing_link_names_the_missing_link() -> None:
    link = LinkModel()
    line3 = Topology(
        "line3",
        ("alice", "relay", "bob"),
        {frozenset(("alice", "relay")): link, frozenset(("relay", "bob")): link},
    )
    with pytest.raises(ApplicationFailure, match="no link between"):
        run_once("qkd", topology=line3)


@pytest.mark.usefixtures("registered")
def test_cli_reports_the_failure_without_a_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "raises_on_alice"]) == 1
    assert "the bug in the application" in capsys.readouterr().err


def test_reference_backend_takes_no_supply_options() -> None:
    with pytest.raises(ValueError, match="no supply options"):
        run_once("qkd", seed=0, supply_options={"timing": "fixed"})
