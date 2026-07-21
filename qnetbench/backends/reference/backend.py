"""The reference backend: a pure-Python, dependency-free implementation of the
api. It is the CI oracle and the reference against which the SeQUeNCe and NetSquid
backends are checked for equivalence — not a headline deliverable, but the only
backend that runs anywhere without registration.
"""

from __future__ import annotations

import itertools
from collections import deque
from collections.abc import Callable

import numpy as np

from qnetbench.api.application import Application
from qnetbench.api.host import (
    ClassicalSocket,
    EntanglementHandle,
    EPRSocket,
    Qubit,
)
from qnetbench.api.types import (
    AppOutcome,
    Basis,
    Demand,
    Duration,
    Gate,
    NodeId,
    Role,
    SimTime,
    ViolationKind,
)
from qnetbench.backends.reference.engine import Engine, Process
from qnetbench.backends.reference.qstate import Register, gate_matrix
from qnetbench.policies.base import Policy
from qnetbench.topology import Topology
from qnetbench.trace.events import (
    AppOutcomeEvent,
    ClassicalMessage,
    ContractViolation,
    EntanglementDelivered,
    EntanglementRequested,
    Event,
    Measurement,
    RunHeader,
)

BACKEND_NAME = "reference"


def _merge_demands(a: Demand, b: Demand) -> Demand:
    """The governing contract for a two-sided rendezvous is the stricter of the
    two sides' demands."""

    def _min_opt(x: float | None, y: float | None) -> float | None:
        vals = [v for v in (x, y) if v is not None]
        return min(vals) if vals else None

    return Demand(
        min_fidelity=max(a.min_fidelity, b.min_fidelity),
        latency_budget=_min_opt(a.latency_budget, b.latency_budget),
        deadline=_min_opt(a.deadline, b.deadline),
        staleness_tolerance=_min_opt(a.staleness_tolerance, b.staleness_tolerance),
        priority=max(a.priority, b.priority),
        purpose=a.purpose,
    )


class _Qubit:
    def __init__(self, register: Register, qid: int) -> None:
        self._reg = register
        self._qid = qid

    def apply(self, gate: Gate, *params: float) -> None:
        self._reg.apply_1q(self._qid, gate_matrix(gate.value, params))

    def cnot(self, target: Qubit) -> None:
        assert isinstance(target, _Qubit)
        self._reg.cnot(self._qid, target._qid)

    def cz(self, target: Qubit) -> None:
        assert isinstance(target, _Qubit)
        self._reg.cz(self._qid, target._qid)

    def measure(self, basis: Basis = Basis.Z) -> int:
        return self._reg.measure(self._qid, basis.value)

    def free(self) -> None:
        self._reg.free(self._qid)


class _ClassicalChannel:
    """A directed FIFO link with fixed latency."""

    def __init__(self, engine: Engine, latency: Duration) -> None:
        self._engine = engine
        self._latency = latency
        self._queue: deque[tuple[float, bytes]] = deque()
        self._waiter: Process | None = None

    def send(self, msg: bytes) -> None:
        deliver_at = self._engine.now + self._latency
        self._queue.append((deliver_at, msg))
        if self._waiter is not None:
            waiter, self._waiter = self._waiter, None
            self._engine.schedule(waiter, self._latency)

    def recv(self) -> bytes:
        while True:
            if self._queue and self._queue[0][0] <= self._engine.now:
                return self._queue.popleft()[1]
            if self._queue:
                self._engine.wait(self._queue[0][0] - self._engine.now)
                continue
            self._waiter = self._engine.current
            self._engine.park()


class _ClassicalSocket:
    def __init__(self, backend: ReferenceBackend, src: NodeId, dst: NodeId) -> None:
        self._backend = backend
        self._src = src
        self._dst = dst

    def send(self, msg: bytes) -> None:
        self._backend._channel(self._src, self._dst).send(msg)
        self._backend._emit(
            ClassicalMessage(t=self._backend.now(), src=self._src, dst=self._dst, n_bytes=len(msg))
        )

    def recv(self) -> bytes:
        return self._backend._channel(self._dst, self._src).recv()


class _Waiter:
    """One side of a not-yet-matched entanglement rendezvous."""

    def __init__(
        self, side: NodeId, proc: Process, n: int, demand: Demand, req_id: int, arrival: SimTime
    ) -> None:
        self.side = side
        self.proc = proc
        self.n = n
        self.demand = demand
        self.req_id = req_id
        self.arrival = arrival
        self.result: list[EntanglementHandle] | None = None


class _EPRSocket:
    def __init__(self, backend: ReferenceBackend, node: NodeId, peer: NodeId) -> None:
        self._backend = backend
        self._node = node
        self._peer = peer

    def request(self, n: int, demand: Demand) -> list[EntanglementHandle]:
        return self._backend._rendezvous(self._node, self._peer, n, demand)


class _HostImpl:
    def __init__(self, backend: ReferenceBackend, node: NodeId, rng: np.random.Generator) -> None:
        self._backend = backend
        self._node = node
        self._rng = rng

    @property
    def node(self) -> NodeId:
        return self._node

    @property
    def rng(self) -> np.random.Generator:
        return self._rng

    def epr_socket(self, peer: NodeId) -> EPRSocket:
        return _EPRSocket(self._backend, self._node, peer)

    def classical_socket(self, peer: NodeId) -> ClassicalSocket:
        return _ClassicalSocket(self._backend, self._node, peer)

    def qalloc(self) -> Qubit:
        return _Qubit(self._backend.register, self._backend.register.alloc())

    def now(self) -> SimTime:
        return self._backend.now()

    def sleep(self, duration: Duration) -> None:
        self._backend.engine.wait(duration)

    def record_measurement(self, basis: Basis, result: int) -> None:
        self._backend._emit(
            Measurement(t=self._backend.now(), node=self._node, basis=basis.value, result=result)
        )


class ReferenceBackend:
    backend_name: str = BACKEND_NAME

    def __init__(
        self,
        topology: Topology,
        seed: int,
        arbitration: str = "native",
        policy: Policy | None = None,
    ) -> None:
        self.topology = topology
        self.seed = seed
        self.arbitration = arbitration
        self.policy = policy
        self.engine = Engine()
        seq = np.random.SeedSequence(seed)
        self._phys_rng = np.random.default_rng(seq.spawn(1)[0])
        self.register = Register(self._phys_rng)
        self._channels: dict[tuple[NodeId, NodeId], _ClassicalChannel] = {}
        self._waiting: dict[frozenset[str], _Waiter] = {}
        self._req_ids = itertools.count()
        self._events: list[Event] = []
        # Deterministic, independent per-node RNG for application randomness.
        node_seeds = seq.spawn(len(topology.nodes) + 1)[1:]
        self._node_rng = {
            node: np.random.default_rng(s)
            for node, s in zip(topology.nodes, node_seeds, strict=True)
        }

    # --- infrastructure ------------------------------------------------------

    def now(self) -> SimTime:
        return self.engine.now

    def _emit(self, event: Event) -> None:
        self._events.append(event)

    def _channel(self, src: NodeId, dst: NodeId) -> _ClassicalChannel:
        key = (src, dst)
        if key not in self._channels:
            self._channels[key] = _ClassicalChannel(self.engine, self._classical_latency(src, dst))
        return self._channels[key]

    # --- physics hooks (overridden by other backends that reuse this engine) --

    def _classical_latency(self, src: NodeId, dst: NodeId) -> float:
        """Classical one-way delay for a directed edge, in seconds."""
        return self.topology.link(src, dst).attempt_latency

    def _sample_pairs(self, node: NodeId, peer: NodeId, pairs: int) -> tuple[float, list[float]]:
        """Return (total generation latency, per-pair delivered fidelities) for a
        batch of `pairs`. The reference backend samples its analytic link model;
        the SeQUeNCe backend replays a supply pre-generated by the simulator."""
        link = self.topology.link(node, peer)
        total_latency = 0.0
        fidelities: list[float] = []
        for _ in range(pairs):
            total_latency += float(self._phys_rng.exponential(link.attempt_latency))
            raw = self._phys_rng.normal(link.link_fidelity, link.fidelity_std)
            fidelities.append(float(np.clip(raw, 0.0, 1.0)))
        return total_latency, fidelities

    # --- entanglement rendezvous + arbitration -------------------------------

    def _rendezvous(
        self, node: NodeId, peer: NodeId, n: int, demand: Demand
    ) -> list[EntanglementHandle]:
        key = frozenset((node, peer))
        other = self._waiting.get(key)
        if other is not None and other.side != node:
            del self._waiting[key]
            return self._generate(matched=other, node=node, peer=peer, n=n, demand=demand)

        req_id = next(self._req_ids)
        self._emit(
            EntanglementRequested(
                t=self.now(), req_id=req_id, src=node, dst=peer, n=n, demand=demand
            )
        )
        waiter = _Waiter(node, self.engine.current, n, demand, req_id, self.now())
        self._waiting[key] = waiter
        self.engine.park()
        assert waiter.result is not None
        return waiter.result

    def _generate(
        self, matched: _Waiter, node: NodeId, peer: NodeId, n: int, demand: Demand
    ) -> list[EntanglementHandle]:
        # In `policy` mode the arbiter would order contending requests here; with
        # single-tenant Phase 0 workloads at most one request is ever pending, so
        # ordering is pass-through. Contention (and thus ranking inversion) is a
        # multi-tenant concern that arrives with the cross-policy evaluation.
        if n != matched.n:
            raise ValueError(
                f"entanglement rendezvous size mismatch on {node!r}↔{peer!r}: "
                f"{node} asked for {n}, peer asked for {matched.n}. Both sides of a "
                "pair request must agree on the count."
            )
        gov = _merge_demands(matched.demand, demand)
        pairs = n

        total_latency, fidelities = self._sample_pairs(node, peer, pairs)
        pair_qubits = [self.register.make_bell_pair(fid) for fid in fidelities]

        request_time = matched.arrival
        delivery_time = self.now() + total_latency
        latency = delivery_time - request_time
        pair_age = 0.0  # fresh generation; pre-provisioned pairs (staleness) come later

        waiter_handles: list[EntanglementHandle] = []
        caller_handles: list[EntanglementHandle] = []
        for (qa, qb), fid in zip(pair_qubits, fidelities, strict=True):
            violations = self._contract_violations(gov, fid, delivery_time, request_time, pair_age)
            self._emit(
                EntanglementDelivered(
                    t=delivery_time,
                    req_id=matched.req_id,
                    actual_fidelity=fid,
                    latency=latency,
                    pair_age=pair_age,
                )
            )
            for kind in violations:
                self._emit(
                    ContractViolation(t=delivery_time, req_id=matched.req_id, violation=kind)
                )
            waiter_handles.append(
                self._build_handle(matched.req_id, qa, fid, latency, pair_age, violations, gov)
            )
            caller_handles.append(
                self._build_handle(matched.req_id, qb, fid, latency, pair_age, violations, gov)
            )

        matched.result = waiter_handles
        self.engine.schedule(matched.proc, total_latency)
        self.engine.wait(total_latency)
        return caller_handles

    def _build_handle(
        self,
        req_id: int,
        qid: int,
        fidelity: float,
        latency: float,
        pair_age: float,
        violations: list[ViolationKind],
        gov: Demand,
    ) -> EntanglementHandle:
        if gov.purpose == "measure":
            outcome = self.register.measure(qid, "Z")
            return EntanglementHandle(
                req_id=req_id,
                fidelity=fidelity,
                latency=latency,
                pair_age=pair_age,
                qubit=None,
                outcome=outcome,
                violations=list(violations),
            )
        return EntanglementHandle(
            req_id=req_id,
            fidelity=fidelity,
            latency=latency,
            pair_age=pair_age,
            qubit=_Qubit(self.register, qid),
            violations=list(violations),
        )

    @staticmethod
    def _contract_violations(
        gov: Demand, fidelity: float, delivery_time: float, request_time: float, pair_age: float
    ) -> list[ViolationKind]:
        violations: list[ViolationKind] = []
        if fidelity < gov.min_fidelity:
            violations.append("fidelity")
        latency = delivery_time - request_time
        if gov.deadline is not None and delivery_time > gov.deadline:
            violations.append("deadline")
        elif gov.latency_budget is not None and latency > gov.latency_budget:
            violations.append("deadline")
        if gov.staleness_tolerance is not None and pair_age > gov.staleness_tolerance:
            violations.append("staleness")
        return violations

    # --- run one application -------------------------------------------------

    def run(
        self, app: Application, cfg: dict[str, object], roles_to_nodes: dict[Role, NodeId]
    ) -> list[Event]:
        outcomes: dict[Role, AppOutcome] = {}

        def make_runner(role: Role, node: NodeId) -> Callable[[], None]:
            def runner() -> None:
                host = _HostImpl(self, node, self._node_rng[node])
                outcomes[role] = app.run(host, role, cfg)

            return runner

        for role in app.roles():
            node = roles_to_nodes[role]
            proc = self.engine.spawn(make_runner(role, node), name=f"{app.name}:{role}")
            self.engine.schedule(proc, 0.0)

        self.engine.run()

        missing = set(roles_to_nodes) - set(outcomes)
        if missing:
            raise RuntimeError(
                f"application {app.name!r} did not complete for roles {sorted(missing)}: "
                "a role is blocked (deadlocked on an entanglement rendezvous or a "
                "classical recv with no matching peer)."
            )

        header = RunHeader(
            t=0.0,
            api_version=_api_version(),
            app=app.name,
            backend=self.backend_name,
            arbitration=self.arbitration,
            topology=self.topology.name,
            seed=self.seed,
        )
        events: list[Event] = [header]
        for role, outcome in outcomes.items():
            events.append(
                AppOutcomeEvent(
                    t=self.now(),
                    role=role,
                    node=roles_to_nodes[role],
                    success=outcome.success,
                    utility=outcome.utility,
                    payload=outcome.payload,
                )
            )
        events.extend(self._events)
        events.sort(key=lambda e: e.t)
        return events


def _api_version() -> str:
    from qnetbench.api import API_VERSION

    return API_VERSION
