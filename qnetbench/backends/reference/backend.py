"""The reference backend: a pure-Python, dependency-free implementation of the
api. It is the CI oracle and the reference against which the SeQUeNCe and NetSquid
backends are checked for equivalence — not a headline deliverable, but the only
backend that runs anywhere without registration.
"""

from __future__ import annotations

import itertools
import math
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
from qnetbench.backends.reference.link import LinkRequest, LinkServer
from qnetbench.backends.reference.qstate import MemoryNoise, Register, gate_matrix
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
    QubitSent,
    RunHeader,
)

BACKEND_NAME = "reference"
_MAXIMALLY_MIXED = 0.25  # the fidelity of a pair that carries no entanglement


def _age_fidelity(f0: float, age: float, coherence_time: float) -> float:
    """Werner fidelity after holding a pair `age` seconds: it decays toward the
    maximally-mixed value 1/4 with time constant `coherence_time`."""
    if age <= 0.0 or math.isinf(coherence_time):
        return f0
    return 0.25 + (f0 - 0.25) * math.exp(-age / coherence_time)


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
        self._reg.settle(self._qid)
        self._reg.apply_1q(self._qid, gate_matrix(gate.value, params))

    def cnot(self, target: Qubit) -> None:
        assert isinstance(target, _Qubit)
        self._reg.settle(self._qid)
        self._reg.settle(target._qid)
        self._reg.cnot(self._qid, target._qid)

    def cz(self, target: Qubit) -> None:
        assert isinstance(target, _Qubit)
        self._reg.settle(self._qid)
        self._reg.settle(target._qid)
        self._reg.cz(self._qid, target._qid)

    def measure(self, basis: Basis = Basis.Z) -> int:
        self._reg.settle(self._qid)
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
            # A message whose delivery time has arrived: take it.
            if self._queue and self._queue[0][0] <= self._engine.now:
                return self._queue.popleft()[1]
            # A message still in flight: wait until it lands, then re-check.
            if self._queue:
                self._engine.wait(self._queue[0][0] - self._engine.now)
                continue
            # Nothing queued: park until a send wakes us (see `send`).
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


class _Transfer:
    """A matched request: both sides are parked until its last pair arrives."""

    def __init__(self, matched: _Waiter, caller: Process, node: NodeId, gov: Demand) -> None:
        self.matched = matched
        self.caller = caller
        self.node = node
        self.gov = gov
        self.waiter_handles: list[EntanglementHandle] = []
        self.caller_handles: list[EntanglementHandle] = []


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
        register = self._backend.register
        qid = register.alloc()
        register.stamp(qid, self.now(), self._node)
        return _Qubit(register, qid)

    def qsend(self, peer: NodeId, qubit: Qubit) -> None:
        self._backend._qsend(self._node, peer, qubit)

    def qrecv(self, peer: NodeId) -> Qubit:
        return self._backend._qrecv(peer, self._node)

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
        pair_age: float = 0.0,
        coherence_time: float = math.inf,
        engine: Engine | None = None,
    ) -> None:
        self.topology = topology
        self.seed = seed
        self.arbitration = arbitration
        self.policy = policy
        # Staleness model: every delivered pair has been held `pair_age` seconds,
        # decohering its fidelity toward the maximally-mixed 1/4 with time constant
        # `coherence_time`. pair_age=0 / coherence_time=inf means fresh pairs.
        self.pair_age = pair_age
        self.coherence_time = coherence_time
        # Contract fields replaced on every request of the run (`run_once` validates
        # them). The trace records the contract in force, so a run stays self-describing.
        self.demand_override: dict[str, object] = {}
        # Everything below until the seeds is set by `qnetbench.tenancy`, which runs several
        # backends on one engine and one link. Defaults give a single application on its own.
        self.engine = engine or Engine()
        self.shared_link: LinkServer | None = None
        self.tenant = ""
        self.queue_wait_aging = False  # a pair ages by its request's time in the queue
        self.arrivals: tuple[float, ...] = ()  # earliest time of each side's k-th request
        self._arrival_counts: dict[NodeId, int] = {}
        self._links: dict[frozenset[str], LinkServer] = {}
        seq = np.random.SeedSequence(seed)
        # Link sampling and quantum measurement must not share a stream. Link
        # sampling draws two values per delivered pair (_sample_pairs), while a
        # backend that replays a pre-generated supply draws none; sharing one
        # generator therefore leaves every subsequent measurement at a different
        # position in the stream, and outcomes stop being comparable across
        # backends at a fixed seed. Separate streams make replay outcome-preserving,
        # which is what Goal G4 asserts.
        phys_seed, register_seed = seq.spawn(2)
        self._phys_rng = np.random.default_rng(phys_seed)
        self.register = Register(np.random.default_rng(register_seed))
        self._channels: dict[tuple[NodeId, NodeId], _ClassicalChannel] = {}
        # Single-qubit transmission rendezvous (qsend blocks until qrecv), one
        # sender/receiver in flight per directed edge — keeps the register small.
        self._qsend_pending: dict[tuple[NodeId, NodeId], tuple[Process, int]] = {}
        self._qrecv_waiting: dict[tuple[NodeId, NodeId], tuple[Process, list[int]]] = {}
        self._waiting: dict[frozenset[str], _Waiter] = {}
        self._req_ids = itertools.count()
        self._events: list[Event] = []
        # Deterministic, independent per-node RNG for application randomness.
        node_seeds = seq.spawn(len(topology.nodes) + 1)[1:]
        self._node_rng = {
            node: np.random.default_rng(s)
            for node, s in zip(topology.nodes, node_seeds, strict=True)
        }
        # Spawned last so that it moves none of the streams above.
        self._memory_seed = seq.spawn(1)[0]
        self._started: tuple[Application, dict[Role, NodeId]] | None = None
        self._outcomes: dict[Role, AppOutcome] = {}
        self._finished_at: SimTime = 0.0

    def enable_memory(self, coherence_time: float, noise: MemoryNoise) -> None:
        """Make qubits decay while they are held. Off by default."""
        self.register.enable_memory(
            self.now, coherence_time, noise, np.random.default_rng(self._memory_seed)
        )

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

    def _qsend(self, src: NodeId, dst: NodeId, qubit: Qubit) -> None:
        assert isinstance(qubit, _Qubit)
        link = self.topology.link(src, dst)
        self.register.depolarize(qubit._qid, link.link_fidelity)  # transmission noise
        self._emit(QubitSent(t=self.now(), src=src, dst=dst, fidelity=link.link_fidelity))
        key = (src, dst)
        waiter = self._qrecv_waiting.pop(key, None)
        if waiter is not None:  # a receiver is already waiting — deliver to it
            recv_proc, slot = waiter
            slot.append(qubit._qid)
            self.register.reassign(qubit._qid, dst)
            self.engine.schedule(recv_proc, link.attempt_latency)
            self.engine.wait(link.attempt_latency)
        else:  # park until a receiver arrives
            self._qsend_pending[key] = (self.engine.current, qubit._qid)
            self.engine.park()

    def _qrecv(self, src: NodeId, dst: NodeId) -> Qubit:
        key = (src, dst)
        latency = self.topology.link(src, dst).attempt_latency
        pending = self._qsend_pending.pop(key, None)
        if pending is not None:  # a sender is already waiting — take its qubit
            send_proc, qid = pending
            self.register.reassign(qid, dst)
            self.engine.schedule(send_proc, latency)
            self.engine.wait(latency)
            return _Qubit(self.register, qid)
        slot: list[int] = []  # park until a sender arrives
        self._qrecv_waiting[key] = (self.engine.current, slot)
        self.engine.park()
        return _Qubit(self.register, slot[0])

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

    def _effective_demand(self, demand: Demand) -> Demand:
        """The contract in force for a request, after any run-level override."""
        if not self.demand_override:
            return demand
        fields = {**demand.model_dump(), **self.demand_override}
        if "latency_budget" in self.demand_override:
            # A budget set for the run replaces an application's own deadline. The
            # deadline would otherwise take precedence and the override would do nothing.
            fields["deadline"] = None
        return Demand.model_validate(fields)

    def _rendezvous(
        self, node: NodeId, peer: NodeId, n: int, demand: Demand
    ) -> list[EntanglementHandle]:
        """An EPR request is a two-sided handshake: the first side to ask parks as
        the edge's waiter; the second side matches it and generates the pairs for
        both. This is what makes `epr.request` on each node return halves of the
        same pairs."""
        demand = self._pace(node, self._effective_demand(demand))
        key = frozenset((node, peer))
        other = self._waiting.get(key)
        if other is not None and other.side != node:
            del self._waiting[key]
            return self._submit(matched=other, node=node, peer=peer, n=n, demand=demand)

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

    def _pace(self, node: NodeId, demand: Demand) -> Demand:
        """Hold this side's k-th request until its scheduled arrival, if it has one.

        Pacing shapes the workload, so it costs nothing physically: an application's
        deadline runs from when the request goes out, and the qubits it holds are not
        charged for the wait. Without this, an application that prepares a qubit before
        asking for a pair would decay merely because the schedule spaces its requests.
        """
        k = self._arrival_counts.get(node, 0)
        self._arrival_counts[node] = k + 1
        if k >= len(self.arrivals):
            return demand
        delay = self.arrivals[k] - self.now()
        if delay <= 0.0:
            return demand
        self.register.pause(node, delay)
        self.engine.wait(delay)
        if demand.deadline is None:
            return demand
        return demand.model_copy(update={"deadline": demand.deadline + delay})

    def _link_for(self, node: NodeId, peer: NodeId) -> LinkServer:
        if self.shared_link is not None:
            return self.shared_link
        key = frozenset((node, peer))
        link = self._links.get(key)
        if link is None:
            # A single application has one request outstanding per link, so this queue
            # never holds more than one and `self.policy` has nothing to order.
            link = self._links[key] = LinkServer(self.engine, self._sample_pairs)
        return link

    def _submit(
        self, matched: _Waiter, node: NodeId, peer: NodeId, n: int, demand: Demand
    ) -> list[EntanglementHandle]:
        if n != matched.n:
            raise ValueError(
                f"entanglement rendezvous size mismatch on {node!r}↔{peer!r}: "
                f"{node} asked for {n}, peer asked for {matched.n}. Both sides of a "
                "pair request must agree on the count."
            )
        gov = _merge_demands(matched.demand, demand)
        transfer = _Transfer(matched, self.engine.current, node, gov)

        def served(
            link_latency: float, sampled: list[float], waited: float, last: bool, stored: float
        ) -> None:
            age = waited if self.queue_wait_aging else stored
            self._deliver(transfer, link_latency, sampled, self.pair_age + age, last, stored)

        def dropped(pairs: int) -> None:
            self._deliver(transfer, 0.0, [_MAXIMALLY_MIXED] * pairs, self.pair_age, True, 0.0)

        self._link_for(node, peer).submit(
            LinkRequest(
                src=node,
                dst=peer,
                remaining=n,
                demand=gov,
                arrival=matched.arrival,
                on_served=served,
                on_dropped=dropped,
                tenant=self.tenant,
            )
        )
        self.engine.park()
        return transfer.caller_handles

    def _deliver(
        self,
        transfer: _Transfer,
        link_latency: float,
        sampled: list[float],
        pair_age: float,
        last: bool,
        stored: float,
    ) -> None:
        matched, gov = transfer.matched, transfer.gov
        prepared = [_age_fidelity(f, pair_age, self.coherence_time) for f in sampled]
        pair_qubits = [self.register.make_bell_pair(fid) for fid in prepared]
        # A stored pair is made fresh and stamped with when it really was made, so its decay
        # reaches the application through `settle`. The trace reports the same decay.
        fidelities = [self.register.aged_fidelity(fid, stored) for fid in prepared]

        request_time = matched.arrival
        delivery_time = self.now() + link_latency
        latency = delivery_time - request_time

        for (qa, qb), fid in zip(pair_qubits, fidelities, strict=True):
            self.register.stamp(qa, delivery_time - stored, matched.side)
            self.register.stamp(qb, delivery_time - stored, transfer.node)
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
            transfer.waiter_handles.append(
                self._build_handle(matched.req_id, qa, fid, latency, pair_age, violations, gov)
            )
            transfer.caller_handles.append(
                self._build_handle(matched.req_id, qb, fid, latency, pair_age, violations, gov)
            )

        # Both sides observe delivery only after the last pair's generation latency
        # elapses, so both resume together.
        if last:
            matched.result = transfer.waiter_handles
            self.engine.schedule(matched.proc, link_latency)
            self.engine.schedule(transfer.caller, link_latency)

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
        self.start(app, cfg, roles_to_nodes)
        self.engine.run()
        return self.collect()

    def start(
        self, app: Application, cfg: dict[str, object], roles_to_nodes: dict[Role, NodeId]
    ) -> None:
        """Spawn the application's roles on the engine, without running it."""
        self._started = (app, roles_to_nodes)

        def make_runner(role: Role, node: NodeId) -> Callable[[], None]:
            def runner() -> None:
                host = _HostImpl(self, node, self._node_rng[node])
                self._outcomes[role] = app.run(host, role, cfg)
                self._finished_at = self.now()

            return runner

        prefix = f"{self.tenant}/" if self.tenant else ""
        for role in app.roles():
            node = roles_to_nodes[role]
            proc = self.engine.spawn(make_runner(role, node), name=f"{prefix}{app.name}:{role}")
            self.engine.schedule(proc, 0.0)

    def collect(self) -> list[Event]:
        """The trace of the application `start` began, once the engine has finished."""
        assert self._started is not None, "call start() first"
        app, roles_to_nodes = self._started
        outcomes = self._outcomes
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
                    t=self._finished_at,
                    role=role,
                    node=roles_to_nodes[role],
                    success=outcome.success,
                    utility=outcome.utility,
                    scores=outcome.scores,
                    payload=outcome.payload,
                )
            )
        events.extend(self._events)
        events.sort(key=lambda e: e.t)
        return events


def _api_version() -> str:
    # Imported lazily to keep `qnetbench.api` free of any dependency on backends.
    from qnetbench.api import API_VERSION

    return API_VERSION
