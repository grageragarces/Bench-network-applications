"""Run one application on one backend under one arbitration mode, over a topology.

This is the single entry point the CLI, the tests, and (later) the cross-policy
sweep all go through."""

from __future__ import annotations

from qnetbench.apps import get_app
from qnetbench.backends.reference import ReferenceBackend
from qnetbench.policies import get_policy
from qnetbench.topology import Topology, line2
from qnetbench.trace.events import Event


def _parse_arbitration(spec: str) -> tuple[str, object | None]:
    if spec == "native":
        return "native", None
    if spec.startswith("policy:"):
        policy = get_policy(spec.split(":", 1)[1])
        return spec, policy
    raise ValueError(f"arbitration must be 'native' or 'policy:<name>', got {spec!r}")


def run_once(
    app_name: str,
    *,
    seed: int = 0,
    backend: str = "reference",
    arbitration: str = "native",
    topology: Topology | None = None,
    cfg: dict[str, object] | None = None,
) -> list[Event]:
    """Execute one run and return its trace as a list of events."""
    app = get_app(app_name)
    topo = topology or line2()
    roles_to_nodes = {role: role for role in app.roles()}
    missing = [n for n in roles_to_nodes.values() if n not in topo.nodes]
    if missing:
        raise ValueError(f"topology {topo.name!r} is missing nodes for roles {missing}")

    if backend != "reference":
        raise NotImplementedError(
            f"backend {backend!r} is not available yet; the SeQUeNCe and NetSquid "
            "backends arrive in Phases 1–2. Only 'reference' is implemented."
        )

    arb_label, policy = _parse_arbitration(arbitration)
    ref = ReferenceBackend(topo, seed=seed, arbitration=arb_label, policy=policy)  # type: ignore[arg-type]
    return ref.run(app, cfg or {}, roles_to_nodes)
