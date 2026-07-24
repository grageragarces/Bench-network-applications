"""Run one application on one backend under one arbitration mode, over a topology.

This is the single entry point the CLI, the tests, and (later) the cross-policy
sweep all go through."""

from __future__ import annotations

import math

from qnetbench.apps import get_app
from qnetbench.backends.reference import ReferenceBackend
from qnetbench.policies import get_policy
from qnetbench.topology import Topology, line2, star
from qnetbench.trace.events import Event


def _default_topology(roles: list[str]) -> Topology:
    """The default topology for an application: a direct link for two roles, or a
    hub-and-spoke star (role[0] = hub) for multipartite applications."""
    if len(roles) == 2:
        return line2(roles[0], roles[1])
    return star(roles[0], list(roles[1:]))


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
    pair_age: float = 0.0,
    coherence_time: float = math.inf,
) -> list[Event]:
    """Execute one run and return its trace as a list of events.

    `pair_age`/`coherence_time` model staleness (used by characterization); they
    are only supported on the reference backend."""
    app = get_app(app_name)
    topo = topology or _default_topology(app.roles())
    roles_to_nodes = {role: role for role in app.roles()}
    missing = [n for n in roles_to_nodes.values() if n not in topo.nodes]
    if missing:
        raise ValueError(f"topology {topo.name!r} is missing nodes for roles {missing}")

    arb_label, policy = _parse_arbitration(arbitration)

    if backend == "reference":
        ref = ReferenceBackend(
            topo,
            seed=seed,
            arbitration=arb_label,
            policy=policy,  # type: ignore[arg-type]
            pair_age=pair_age,
            coherence_time=coherence_time,
        )
        return ref.run(app, cfg or {}, roles_to_nodes)

    if (pair_age, coherence_time) != (0.0, math.inf):
        raise NotImplementedError(
            f"pair aging (staleness) is only modelled on the reference backend, not {backend!r}"
        )

    if backend == "sequence":
        try:
            from qnetbench.backends.sequence import SequenceBackend
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "the 'sequence' backend needs the optional SeQUeNCe dependency; "
                "install it with: pip install qnetbench[sequence]"
            ) from exc
        seq = SequenceBackend(topo, seed=seed, arbitration=arb_label, policy=policy)  # type: ignore[arg-type]
        return seq.run(app, cfg or {}, roles_to_nodes)

    if backend == "netsquid":
        try:
            from qnetbench.backends.netsquid import NetSquidBackend
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "the 'netsquid' backend needs the optional NetSquid dependency; "
                "register at netsquid.org and install with: "
                "pip install --extra-index-url https://pypi.netsquid.org qnetbench[netsquid]"
            ) from exc
        nsq = NetSquidBackend(topo, seed=seed, arbitration=arb_label, policy=policy)  # type: ignore[arg-type]
        return nsq.run(app, cfg or {}, roles_to_nodes)

    raise NotImplementedError(
        f"unknown backend {backend!r}; available: 'reference', 'sequence', 'netsquid'."
    )
