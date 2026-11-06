"""Several applications running at once on one shared link, with a policy choosing who is
served next.

`qnetbench.contention` models this as a queue of demands and assumes what each is worth.
Here the applications really run, so what comes back is measured. The same mixes can go
through both, which shows where the queue predicts execution and where it does not.

The modelling decisions are kept changeable on purpose. Four are fields of `ExecutionModel`,
whose defaults are:

    1. arrivals         "paced": a tenant's k-th request goes out no earlier than a schedule,
                        which gives a like-for-like comparison with the queue model.
                        Alternative: "closed_loop", all start together with no schedule.
    2. aging            "held_qubits": a new pair is fresh, and qubits decay while held.
                        Alternatives: "queue_wait" as in the queue model, or "none".
       memory_noise     "dephasing" on held qubits. Alternative: "depolarizing".
    3. missed_deadline  "serve_late": served anyway, with a violation in the trace.
                        Alternative: "drop", where the request uses no link capacity and the
                        application gets a maximally mixed pair, since none can handle
                        being refused one.
    4. service_unit     "pair": the policy chooses again after every pair.
                        Alternative: "request", where a request keeps the link until done.

The other two are structural, and changing them means changing code:

    5. One trace per tenant, each valid under the unchanged trace schema, plus a small
       manifest (`TenantsRun.write`). A single merged trace needs a tenant field on each
       event, which is a contract change.
    6. Two-role applications on one link (`_check_scope`). Multipartite tenants need a
       decision about how their edges map onto physical links.

Tenants do not compete for memory qubits or node time, only for the link.
"""

from __future__ import annotations

import json
import math
import typing
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np

from qnetbench.api.application import Application
from qnetbench.api.types import Demand
from qnetbench.apps import get_app
from qnetbench.backends.reference import ReferenceBackend
from qnetbench.backends.reference.backend import _age_fidelity
from qnetbench.backends.reference.engine import Engine
from qnetbench.backends.reference.link import LinkRequest, LinkServer, MissedDeadline, ServiceUnit
from qnetbench.backends.reference.qstate import MemoryNoise
from qnetbench.characterize.provenance import write_atomic
from qnetbench.contention import ContentionResult, Tenant, arrival_times
from qnetbench.harness.runner import _checked_override, _parse_arbitration
from qnetbench.metrics.report import compute_report
from qnetbench.policies.base import Policy
from qnetbench.topology import LinkModel, default_topology, line2
from qnetbench.trace.events import ContractViolation, EntanglementRequested, Event
from qnetbench.trace.io import write_trace

Arrivals = Literal["paced", "closed_loop"]
Aging = Literal["held_qubits", "queue_wait", "none"]
Service = Literal["on_demand", "ticks"]
SupplyName = Literal["reference", "sequence", "netsquid"]


@dataclass(frozen=True)
class ExecutionModel:
    """How concurrent execution behaves. See the module docstring for why each default."""

    arrivals: Arrivals = "paced"
    aging: Aging = "held_qubits"
    memory_noise: MemoryNoise = "dephasing"
    missed_deadline: MissedDeadline = "serve_late"
    service_unit: ServiceUnit = "pair"
    # Not one of the six decisions. "ticks" is the queue model's clock of one pair per
    # period, kept so the two can be compared. "on_demand" takes the supply's own timing.
    service: Service = "on_demand"

    def __post_init__(self) -> None:
        hints = typing.get_type_hints(type(self))
        for name, value in asdict(self).items():
            allowed = typing.get_args(hints[name])
            if value not in allowed:
                raise ValueError(f"{name} must be one of {allowed}, got {value!r}")


# Everything set the way `qnetbench.contention` assumes, for measuring the distance to it.
AS_QUEUE_MODEL = ExecutionModel(aging="queue_wait", missed_deadline="drop", service="ticks")


@dataclass(frozen=True)
class TenantSpec:
    """One application instance on the shared link."""

    name: str
    app: str
    cfg: Mapping[str, object] = field(default_factory=dict)
    arrivals: tuple[float, ...] = ()  # earliest time of each k-th request; empty means none
    demand_override: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TenantsRun:
    """One trace per tenant, and what produced them."""

    traces: dict[str, list[Event]]
    tenants: tuple[TenantSpec, ...]
    arbitration: str
    seed: int
    model: ExecutionModel
    link: LinkModel
    supply: str
    coherence_time: float

    def manifest(self) -> dict[str, object]:
        return {
            "arbitration": self.arbitration,
            "seed": self.seed,
            "supply": self.supply,
            "model": asdict(self.model),
            "link": asdict(self.link),
            "coherence_time": None if math.isinf(self.coherence_time) else self.coherence_time,
            "tenants": [
                {"name": t.name, "app": t.app, "trace": f"{t.name}.jsonl"} for t in self.tenants
            ],
        }

    def write(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, events in self.traces.items():
            write_trace(out_dir / f"{name}.jsonl", events)
        write_atomic(out_dir / "manifest.json", json.dumps(self.manifest(), indent=2) + "\n")


def _check_scope(tenants: Sequence[TenantSpec]) -> dict[str, Application]:
    names = [t.name for t in tenants]
    if not names:
        raise ValueError("need at least one tenant")
    if len(set(names)) != len(names):
        raise ValueError(f"tenant names must be unique, got {names}")
    apps: dict[str, Application] = {}
    for tenant in tenants:
        app = get_app(tenant.app)
        if len(app.roles()) != 2:
            raise NotImplementedError(
                f"{tenant.app!r} has {len(app.roles())} roles. Concurrent execution covers "
                "two-role applications on one link (decision 6 in qnetbench.tenancy)."
            )
        apps[tenant.name] = app
    return apps


def _tenant_seed(seed: int, index: int, count: int) -> int:
    if count == 1:
        return seed  # so that one tenant reproduces `run_once` exactly
    return int(np.random.SeedSequence([seed, index]).generate_state(1)[0])


def _supply_backend(supply: str, link: LinkModel, seed: int) -> ReferenceBackend:
    topology = line2(link=link)
    if supply == "reference":
        return ReferenceBackend(topology, seed=seed)
    if supply == "sequence":
        from qnetbench.backends.sequence import SequenceBackend

        return SequenceBackend(topology, seed=seed)
    if supply == "netsquid":
        from qnetbench.backends.netsquid import NetSquidBackend

        return NetSquidBackend(topology, seed=seed)
    raise ValueError(f"supply must be one of {typing.get_args(SupplyName)}, got {supply!r}")


def run_tenants(
    tenants: Sequence[TenantSpec],
    *,
    seed: int = 0,
    arbitration: str = "native",
    link: LinkModel | None = None,
    classical_latency: float | None = None,
    coherence_time: float = math.inf,
    model: ExecutionModel | None = None,
    supply: str = "reference",
) -> TenantsRun:
    """Run `tenants` together, sharing one link, and return a trace for each.

    `link` describes entanglement generation. Its `attempt_latency` is also the classical
    delay unless `classical_latency` says otherwise, as in `run_once`.

    `coherence_time` is what the model's `aging` applies. For "queue_wait" it is the time
    constant of a pair's fidelity, and for "held_qubits" it is each qubit's own, so a pair
    held on both sides decays twice as fast.

    Fixing `seed` fixes the supply, so policies are compared on the same sequence of pairs.
    """
    model = model or ExecutionModel()
    link = link or LinkModel()
    apps = _check_scope(tenants)
    label, policy = _parse_arbitration(arbitration)

    engine = Engine()
    supplier = _supply_backend(supply, link, seed)
    server = LinkServer(
        engine,
        lambda _src, _dst, pairs: supplier._sample_pairs("alice", "bob", pairs),
        policy=typing.cast("Policy | None", policy),
        service_unit=model.service_unit,
        missed_deadline=model.missed_deadline,
        period=link.attempt_latency if model.service == "ticks" else None,
    )
    tenant_link = (
        link
        if classical_latency is None
        else LinkModel(classical_latency, link.link_fidelity, link.fidelity_std)
    )

    backends: dict[str, ReferenceBackend] = {}
    for index, tenant in enumerate(tenants):
        app = apps[tenant.name]
        roles = app.roles()
        backend = ReferenceBackend(
            default_topology(roles, link=tenant_link),
            seed=_tenant_seed(seed, index, len(tenants)),
            arbitration=label,
            coherence_time=coherence_time if model.aging == "queue_wait" else math.inf,
            engine=engine,
        )
        backend.shared_link = server
        backend.tenant = tenant.name
        backend.queue_wait_aging = model.aging == "queue_wait"
        backend.demand_override = _checked_override(dict(tenant.demand_override))
        if model.arrivals == "paced":
            backend.arrivals = tenant.arrivals
        if model.aging == "held_qubits" and not math.isinf(coherence_time):
            backend.enable_memory(coherence_time, model.memory_noise)
        backend.start(app, dict(tenant.cfg), {role: role for role in roles})
        backends[tenant.name] = backend

    engine.run()

    return TenantsRun(
        traces={name: backend.collect() for name, backend in backends.items()},
        tenants=tuple(tenants),
        arbitration=label,
        seed=seed,
        model=model,
        link=link,
        supply=supply,
        coherence_time=coherence_time,
    )


def contract_satisfaction(
    events: Sequence[Event], *, ignore: Sequence[str] = ("staleness",)
) -> float:
    """The fraction of a trace's requests with no contract violation, as `simulate` scores
    them. Staleness is ignored by default because the queue model does not check it."""
    requested = {e.req_id for e in events if isinstance(e, EntanglementRequested)}
    if not requested:
        return 1.0
    failed = {
        e.req_id
        for e in events
        if isinstance(e, ContractViolation) and e.violation not in ignore
    }
    return 1.0 - len(failed & requested) / len(requested)


def application_utility(events: Sequence[Event]) -> float:
    """What the application itself reported, as the metrics report defines it."""
    return compute_report(events).app_utility


def queue_model_on_link(
    tenants: Sequence[Tenant],
    policy: Policy,
    *,
    capacity: float,
    link_fidelity: float,
    coherence_time: float,
) -> ContentionResult:
    """`contention.simulate`, computed by the link server with no applications running.

    It has to give the same answer, which is what makes the server trustworthy as the
    thing the applications then run on. Any gap between the queue model and execution is
    therefore down to the applications and the physics, not the server.
    """
    engine = Engine()
    server = LinkServer(
        engine,
        lambda _src, _dst, _pairs: (0.0, [link_fidelity]),
        policy=policy,
        service_unit="pair",
        missed_deadline="drop",
        period=1.0 / capacity,
    )
    arrivals = sorted(
        ((when, tenant) for tenant in tenants for when in arrival_times(tenant)),
        key=lambda item: item[0],
    )
    met: list[tuple[str, bool]] = []

    def enter(when: float, tenant: Tenant) -> None:
        deadline = when + tenant.budget if tenant.budget is not None else None
        limit = deadline if deadline is not None else math.inf

        def served(_latency: float, fidelities: list[float], waited: float, _last: bool) -> None:
            delivered = _age_fidelity(fidelities[0], waited, coherence_time)
            met.append((tenant.app, delivered >= tenant.min_fidelity and engine.now <= limit))

        def dropped(_pairs: int) -> None:
            met.append((tenant.app, False))

        request = LinkRequest(
            src="t",
            dst="l",
            remaining=1,
            demand=Demand(min_fidelity=tenant.min_fidelity, deadline=deadline),
            arrival=when,
            on_served=served,
            on_dropped=dropped,
        )
        engine.call_at(when, lambda: server.submit(request))

    for when, tenant in arrivals:
        enter(when, tenant)
    engine.run()

    result = ContentionResult(policy=policy.name)
    if met:
        result.aggregate_utility = sum(ok for _, ok in met) / len(met)
    result.violation_rate = 1.0 - result.aggregate_utility
    for app in {app for app, _ in met}:
        outcomes = [ok for name, ok in met if name == app]
        result.per_app[app] = sum(outcomes) / len(outcomes)
    return result
