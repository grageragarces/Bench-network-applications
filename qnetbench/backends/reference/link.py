"""The entanglement link as a server: requests queue, and pairs are made one service at a time.

A single application never queues, because it has one request outstanding per link. The
same code then runs several tenants over one shared link, where a `Policy` decides who is
served next. `run_once` goes through here too, so `qnetbench corpus --check` covers it.

The server is event driven and owns no thread. Generation runs in whichever context
submitted the request or released the link, and only one context runs at a time.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from qnetbench.api.types import Demand, NodeId, SimTime
from qnetbench.backends.reference.engine import Engine
from qnetbench.policies.base import PendingRequest, Policy

ServiceUnit = Literal["pair", "request"]
MissedDeadline = Literal["serve_late", "drop"]
StoredPair = Literal["newest", "oldest"]
Supply = Callable[[NodeId, NodeId, int], tuple[float, list[float]]]


@dataclass(eq=False)
class LinkRequest:
    """A request both sides have asked for, waiting for or receiving its pairs."""

    src: NodeId
    dst: NodeId
    remaining: int
    demand: Demand
    arrival: SimTime
    # (latency, fidelities, seconds waited before this service, is this the last service,
    # seconds the pair had already been stored when it was handed over)
    on_served: Callable[[float, list[float], float, bool, float], None]
    on_dropped: Callable[[int], None]  # called with the number of pairs not delivered
    tenant: str = ""
    link_id: int = -1

    def effective_deadline(self) -> float:
        return self.pending().effective_deadline()

    def pending(self) -> PendingRequest:
        return PendingRequest(
            req_id=self.link_id,
            src=self.src,
            dst=self.dst,
            n=self.remaining,
            demand=self.demand,
            request_time=self.arrival,
            tenant=self.tenant,
        )


class RequestServer(Protocol):
    """What an application's backend needs from whatever serves its pairs: one link or a switch."""

    def submit(self, request: LinkRequest) -> None: ...


class LinkServer:
    """One physical link.

    `period=None` is on-demand generation: the next service starts as soon as the link is
    free and takes as long as `supply` says. A number is a fixed clock with one pair per
    period at multiples of it, which is what `qnetbench.contention` assumes. A tick with
    nothing to serve is simply lost.

    `storage=n` is a free-running link instead. It generates whether or not anyone has asked,
    on the supply's own timeline, and keeps the newest `n` pairs. A stored pair ages only while
    the link is ahead of demand. `stored_pair` says which one a request takes. It ignores `period`,
    and always serves pair by pair.
    """

    def __init__(
        self,
        engine: Engine,
        supply: Supply,
        *,
        policy: Policy | None = None,
        service_unit: ServiceUnit = "request",
        missed_deadline: MissedDeadline = "serve_late",
        period: float | None = None,
        storage: int | None = None,
        stored_pair: StoredPair = "newest",
        ends: tuple[NodeId, NodeId] = ("alice", "bob"),
    ) -> None:
        self._storage = storage
        self._stored_pair = stored_pair
        self._ends = ends
        self._stock: list[tuple[float, float]] = []  # (made at, fidelity), oldest first
        self._engine = engine
        self._supply = supply
        self._policy = policy
        self._service_unit = service_unit
        self._missed_deadline = missed_deadline
        self._period = period
        self._queue: list[LinkRequest] = []  # in order of submission
        self._ids = itertools.count()
        self._busy = False  # generating, or waiting for the next tick
        self._armed = False  # a tick is already booked
        self._next_tick = 0

    def submit(self, request: LinkRequest) -> None:
        request.link_id = next(self._ids)
        self._queue.append(request)
        self._advance()

    def start(self) -> None:
        """Begin generating on a free-running link. Does nothing on any other."""
        if self._storage is not None:
            self._make_next()

    def _make_next(self) -> None:
        gap, fidelities = self._supply(*self._ends, 1)
        self._engine.call_later(gap, lambda: self._pair_made(fidelities[0]))

    def _pair_made(self, fidelity: float) -> None:
        assert self._storage is not None
        self._stock.append((self._engine.now, fidelity))
        del self._stock[: -self._storage]  # the oldest pairs are discarded
        self._serve_from_stock(self._engine.now)
        # Nothing waiting and nothing else due means the run is over, or is deadlocked and
        # will be reported as such. Generating on would never end.
        if self._queue or self._engine.has_pending():
            self._make_next()

    def _serve_from_stock(self, now: float) -> None:
        while self._stock:
            self._drop_expired(now)
            if not self._queue:
                return
            chosen = self._choose(now)
            made_at, fidelity = self._stock.pop(-1 if self._stored_pair == "newest" else 0)
            self._tell_policy(chosen, [fidelity], now)
            chosen.remaining -= 1
            finished = chosen.remaining == 0
            if finished:
                self._queue.remove(chosen)
            chosen.on_served(0.0, [fidelity], now - chosen.arrival, finished, now - made_at)

    def _drop_expired(self, now: float) -> None:
        if self._missed_deadline == "drop":
            for request in [r for r in self._queue if r.effective_deadline() < now]:
                self._queue.remove(request)
                request.on_dropped(request.remaining)

    def _advance(self) -> None:
        if self._storage is not None:
            self._serve_from_stock(self._engine.now)
            return
        if self._busy or self._armed or not self._queue:
            return
        if self._period is None:
            self._serve(self._engine.now)
            return
        tick = max(self._next_tick, self._first_tick_at_or_after(self._engine.now))
        self._armed = True
        self._engine.call_at(tick * self._period, lambda: self._on_tick(tick))

    def _first_tick_at_or_after(self, when: float) -> int:
        assert self._period is not None
        tick = int(when / self._period)
        while tick * self._period < when:
            tick += 1
        return tick

    def _on_tick(self, tick: int) -> None:
        assert self._period is not None
        self._armed = False
        self._next_tick = tick + 1
        # The exact grid time, so comparisons do not pick up rounding from the event queue.
        self._serve(tick * self._period)

    def _serve(self, now: float) -> None:
        self._drop_expired(now)
        if not self._queue:
            return
        chosen = self._choose(now)
        pairs = chosen.remaining if self._service_unit == "request" else 1
        latency, fidelities = self._supply(chosen.src, chosen.dst, pairs)
        self._tell_policy(chosen, fidelities, now + (0.0 if self._period is not None else latency))
        chosen.remaining -= pairs
        finished = chosen.remaining == 0
        if finished:
            self._queue.remove(chosen)
        self._busy = True
        # Book the release before the delivery wakes anyone, so the link is already free
        # when the woken applications ask for their next pair.
        if self._period is None:
            self._engine.call_later(latency, self._release)
        else:
            latency = 0.0  # the pair is ready on the tick
            self._engine.call_at(self._next_tick * self._period, self._release)
        chosen.on_served(latency, fidelities, now - chosen.arrival, finished, 0.0)

    def _choose(self, now: float) -> LinkRequest:
        if self._policy is None or len(self._queue) == 1:
            return self._queue[0]  # `native` is first come, first served
        order = self._policy.order([r.pending() for r in self._queue], now)
        by_id = {r.link_id: r for r in self._queue}
        return by_id[order[0]]

    def _tell_policy(self, request: LinkRequest, fidelities: list[float], at: float) -> None:
        hook = getattr(self._policy, "on_delivery", None)
        if hook is not None:
            for fidelity in fidelities:
                hook(request.pending(), fidelity, at)

    def _release(self) -> None:
        self._busy = False
        self._advance()
