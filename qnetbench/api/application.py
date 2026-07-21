"""The application contract. An application is written once here and runs on any
backend, under any arbitration mode."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from qnetbench.api.host import Host
from qnetbench.api.types import AppOutcome, Role


@runtime_checkable
class Application(Protocol):
    """A benchmark application.

    `roles()` names the participants (e.g. ["alice", "bob"]); the harness maps
    each role onto a node and calls `run` once per role, concurrently.
    """

    name: str

    def roles(self) -> list[Role]: ...
    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome: ...
