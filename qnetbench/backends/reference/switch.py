"""A star of elementary links meeting at a switch, serving end-to-end requests.

Each tenant's two roles sit on two leaves of the star. Its end-to-end pair needs one pair on
each leaf's link to the hub, which the switch swaps. The swap belongs to the network, not the
application, so any two-role application can be a tenant unchanged.

A `Policy` orders the waiting requests, as on one link. The switch then walks that order and
starts every request whose two legs are both idle, so requests on disjoint leaves are served
at the same time, which is what a switch adds over one link. Both legs generate in parallel. The
pair that arrives first waits in the hub's memory for the other, and decays meanwhile if the hub
has a finite coherence time. Once both are there, the switch measures them, which takes no time,
and announces the result to the leaves, which takes one classical delay. The end-to-end pair is
delivered then, and the legs are free again from the swap.

The hub has one memory per leg and an unlimited Bell-state measurement. Policies decide order
and nothing else: they do not choose which matching of legs to serve.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping

from qnetbench.api.types import NodeId
from qnetbench.backends.reference.backend import _age_fidelity, _bell_weights
from qnetbench.backends.reference.engine import Engine
from qnetbench.backends.reference.link import LinkRequest, MissedDeadline, Supply
from qnetbench.policies.base import Policy

Weights = tuple[float, float, float, float]  # Bell-diagonal (Φ+, Ψ+, Φ-, Ψ-)

HUB: NodeId = "hub"


def leg_weights(sampled: float, prepared: float, noise: str) -> Weights:
    """A leg's pair as Bell-diagonal weights, Werner unless `noise` gives another shape."""
    shaped = _bell_weights(sampled, prepared, noise)
    if shaped is not None:
        return shaped
    rest = (1.0 - prepared) / 3.0
    return (prepared, rest, rest, rest)


def swap(first: Weights, second: Weights) -> Weights:
    """The Bell-diagonal state left on the outer qubits after swapping two Bell-diagonal pairs.

    In the order (Φ+, Ψ+, Φ-, Ψ-) the Bell states are Φ+ with I, X, Z or Y applied to one half,
    and those Paulis multiply, up to a phase, as their indices XOR. A swap composes the two errors,
    so the weights convolve under XOR. Two Werner pairs give F1 F2 + (1 - F1)(1 - F2) / 3.
    """
    out = [0.0, 0.0, 0.0, 0.0]
    for i, a in enumerate(first):
        for j, b in enumerate(second):
            out[i ^ j] += a * b
    return (out[0], out[1], out[2], out[3])


class SwitchServer:
    """End-to-end requests over a star, served by a switch at its hub."""

    def __init__(
        self,
        engine: Engine,
        legs: Mapping[NodeId, Supply],
        placement: Mapping[str, tuple[NodeId, NodeId]],
        *,
        policy: Policy | None = None,
        missed_deadline: MissedDeadline = "serve_late",
        announce_delay: float = 0.0,
        hub_coherence: float = math.inf,
        noise: str = "depolarizing",
    ) -> None:
        for tenant, (a, b) in placement.items():
            if a == b:
                raise ValueError(f"tenant {tenant!r} needs two different leaves, got {a!r} twice")
            for leaf in (a, b):
                if leaf not in legs:
                    raise ValueError(f"tenant {tenant!r} is placed on {leaf!r}, which has no leg")
        self._engine = engine
        self._legs = dict(legs)
        self._placement = dict(placement)
        self._policy = policy
        self._missed_deadline = missed_deadline
        self._announce_delay = announce_delay
        self._hub_coherence = hub_coherence
        self._noise = noise
        self._queue: list[LinkRequest] = []  # in order of submission
        self._ids = itertools.count()
        self._busy: set[NodeId] = set()

    def submit(self, request: LinkRequest) -> None:
        if request.tenant not in self._placement:
            raise ValueError(f"tenant {request.tenant!r} has no placement on the star")
        request.link_id = next(self._ids)
        self._queue.append(request)
        self._advance()

    def start(self) -> None:
        """Nothing to start: legs generate on demand."""

    def _advance(self) -> None:
        now = self._engine.now
        self._drop_expired(now)
        for request in self._ordered(now):
            a, b = self._placement[request.tenant]
            if a not in self._busy and b not in self._busy:
                self._serve(request, a, b, now)

    def _ordered(self, now: float) -> list[LinkRequest]:
        if self._policy is None or len(self._queue) <= 1:
            return list(self._queue)  # `native` is first come, first served
        order = self._policy.order([r.pending() for r in self._queue], now)
        by_id = {r.link_id: r for r in self._queue}
        return [by_id[i] for i in order]

    def _drop_expired(self, now: float) -> None:
        if self._missed_deadline == "drop":
            for request in [r for r in self._queue if r.effective_deadline() < now]:
                self._queue.remove(request)
                request.on_dropped(request.remaining)

    def _serve(self, request: LinkRequest, a: NodeId, b: NodeId, now: float) -> None:
        latency_a, (fidelity_a,) = self._legs[a](a, HUB, 1)
        latency_b, (fidelity_b,) = self._legs[b](b, HUB, 1)
        swapped_at = max(latency_a, latency_b)
        # The pair that arrived first waits for the other, held at the hub and at its leaf, so
        # it decays with twice the rate of one qubit.
        aged_a = _age_fidelity(fidelity_a, swapped_at - latency_a, self._hub_coherence / 2)
        aged_b = _age_fidelity(fidelity_b, swapped_at - latency_b, self._hub_coherence / 2)
        end_to_end = swap(
            leg_weights(fidelity_a, aged_a, self._noise),
            leg_weights(fidelity_b, aged_b, self._noise),
        )[0]
        latency = swapped_at + self._announce_delay
        hook = getattr(self._policy, "on_delivery", None)
        if hook is not None:
            hook(request.pending(), end_to_end, now + latency)
        request.remaining -= 1
        finished = request.remaining == 0
        if finished:
            self._queue.remove(request)
        self._busy.update((a, b))
        # Book the release before the delivery wakes anyone, so the legs are already free
        # when the woken applications ask for their next pair.
        self._engine.call_later(swapped_at, lambda: self._release(a, b))
        request.on_served(latency, [end_to_end], now - request.arrival, finished, 0.0)

    def _release(self, a: NodeId, b: NodeId) -> None:
        self._busy.difference_update((a, b))
        self._advance()
