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
from typing import Literal

from qnetbench.api.types import Demand, NodeId, SimTime
from qnetbench.backends.reference.engine import Engine
from qnetbench.policies.base import PendingRequest, Policy

ServiceUnit = Literal["pair", "request"]
MissedDeadline = Literal["serve_late", "drop"]
Supply = Callable[[NodeId, NodeId, int], tuple[float, list[float]]]


@dataclass(eq=False)
class LinkRequest:
    """A request both sides have asked for, waiting for or receiving its pairs."""

    src: NodeId
    dst: NodeId
    remaining: int
    demand: Demand
    arrival: SimTime
    # (latency, fidelities, seconds waited before this service, is this the last service)
    on_served: Callable[[float, list[float], float, bool], None]
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


class LinkServer:
    """One physical link.

    `period=None` is on-demand generation: the next service starts as soon as the link is
    free and takes as long as `supply` says. A number is a fixed clock with one pair per
    period at multiples of it, which is what `qnetbench.contention` assumes. A tick with
    nothing to serve is simply lost.
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
    ) -> None:
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

    def _advance(self) -> None:
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
        if self._missed_deadline == "drop":
            for request in [r for r in self._queue if r.effective_deadline() < now]:
                self._queue.remove(request)
                request.on_dropped(request.remaining)
        if not self._queue:
            return
        chosen = self._choose(now)
        pairs = chosen.remaining if self._service_unit == "request" else 1
        latency, fidelities = self._supply(chosen.src, chosen.dst, pairs)
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
        chosen.on_served(latency, fidelities, now - chosen.arrival, finished)

    def _choose(self, now: float) -> LinkRequest:
        if self._policy is None or len(self._queue) == 1:
            return self._queue[0]  # `native` is first come, first served
        order = self._policy.order([r.pending() for r in self._queue], now)
        by_id = {r.link_id: r for r in self._queue}
        return by_id[order[0]]

    def _release(self) -> None:
        self._busy = False
        self._advance()
