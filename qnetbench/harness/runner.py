"""Run one application on one backend under one arbitration mode, over a topology.

This is the single entry point the CLI, the tests, and (later) the cross-policy
sweep all go through."""

from __future__ import annotations

import math

from qnetbench.api.types import Demand
from qnetbench.apps import get_app
from qnetbench.backends.reference import ReferenceBackend
from qnetbench.policies import get_policy
from qnetbench.topology import Topology, default_topology
from qnetbench.trace.events import Event

# What `run_once(demand_override=...)` may replace. `purpose` is left out because it
# decides whether an application receives a qubit at all, so changing it would break
# the protocol rather than vary its contract. `deadline` is left out because it is an
# absolute time each application computes per request; use `latency_budget` instead.
CONTRACT_OVERRIDES = frozenset(
    {"min_fidelity", "latency_budget", "staleness_tolerance", "priority"}
)


def _checked_override(demand_override: dict[str, object] | None) -> dict[str, object]:
    override = dict(demand_override or {})
    unknown = set(override) - CONTRACT_OVERRIDES
    if unknown:
        raise ValueError(
            f"cannot override contract field(s) {sorted(unknown)}; "
            f"allowed: {sorted(CONTRACT_OVERRIDES)}"
        )
    Demand.model_validate(override)  # reject out-of-range values before the run starts
    return override


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
    demand_override: dict[str, object] | None = None,
) -> list[Event]:
    """Execute one run and return its trace as a list of events.

    `pair_age`/`coherence_time` model staleness (used by characterization); they
    are only supported on the reference backend.

    `demand_override` replaces contract fields on every entanglement request, which
    is how to vary a contract without editing the application. Applications that use
    `qsend` make no entanglement requests, so it has no effect on them. A
    `latency_budget` also clears the application's own deadline. The trace records
    the contract in force."""
    override = _checked_override(demand_override)
    app = get_app(app_name)
    topo = topology or default_topology(app.roles())
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
        ref.demand_override = override
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
        seq.demand_override = override
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
        nsq.demand_override = override
        return nsq.run(app, cfg or {}, roles_to_nodes)

    raise NotImplementedError(
        f"unknown backend {backend!r}; available: 'reference', 'sequence', 'netsquid'."
    )
