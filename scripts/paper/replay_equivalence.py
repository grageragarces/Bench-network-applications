#!/usr/bin/env python3
"""Is the replay model outcome-preserving? (Sec. VI)

The simulator backends do not execute applications. They extract a delivered-pair
stream from the external simulator and replay it through the reference engine,
which runs the protocol. Section VI therefore mixes two questions whenever it
compares backends: whether the backends supply different entanglement (they do,
by design) and whether *replaying* a supply distorts the computation performed on
it (it should not).

This script isolates the second. For each core application it runs natively on
the reference backend, records the entanglement supply that run produced, and
replays exactly that supply back through the same engine. Any difference in the
application outcome is attributable to the replay mechanism alone, because the
supply and the engine are identical by construction.

    python scripts/paper/replay_equivalence.py > scripts/paper/data/replay_equivalence.txt
"""

from __future__ import annotations

from collections import defaultdict

from qnetbench.api.types import NodeId
from qnetbench.apps import available_apps, get_app
from qnetbench.backends.replay import ReplayBackend, Supply
from qnetbench.harness.runner import _default_topology
from qnetbench.metrics import compute_report
from qnetbench.topology import Topology
from qnetbench.trace.events import (
    AppOutcomeEvent,
    EntanglementDelivered,
    EntanglementRequested,
    Event,
)

SEED = 0


def recorded_supplies(events: list[Event]) -> dict[frozenset[str], Supply]:
    """Reconstruct the per-edge delivered-pair stream from a native run's trace.

    Deliveries carry a request id rather than an edge, so they are attributed via
    the request that asked for them.
    """
    edge_of: dict[int, frozenset[str]] = {}
    for ev in events:
        if isinstance(ev, EntanglementRequested):
            edge_of[ev.req_id] = frozenset((ev.src, ev.dst))
    times: dict[frozenset[str], list[float]] = defaultdict(list)
    fids: dict[frozenset[str], list[float]] = defaultdict(list)
    for ev in events:
        if isinstance(ev, EntanglementDelivered) and ev.req_id in edge_of:
            edge = edge_of[ev.req_id]
            times[edge].append(ev.t)
            fids[edge].append(ev.actual_fidelity)
    supplies = {}
    for edge, ts in times.items():
        gaps = [ts[0]] + [b - a for a, b in zip(ts, ts[1:], strict=False)]
        supplies[edge] = Supply(
            inter_arrivals=gaps, fidelities=fids[edge], classical_latency=0.0
        )
    return supplies


class _RecordedBackend(ReplayBackend):
    """Replays a supply captured from a native reference run."""

    backend_name = "recorded"

    def __init__(self, topology: Topology, seed: int, supplies) -> None:
        self._recorded = supplies
        super().__init__(topology, seed=seed)

    def _make_supply(self, node: NodeId, peer: NodeId) -> Supply:
        edge = frozenset((node, peer))
        found = self._recorded.get(edge)
        if found is None:  # an edge the native run never used
            return Supply(inter_arrivals=[], fidelities=[], classical_latency=0.0)
        return found


def outcome(events: list[Event]) -> tuple[float, tuple[tuple[str, bool], ...]]:
    report = compute_report(events)
    roles = tuple(
        sorted((e.role, e.success) for e in events if isinstance(e, AppOutcomeEvent))
    )
    return report.app_utility, roles


def main() -> None:
    print("Replay outcome-preservation: native reference run vs. the same supply")
    print(f"replayed through the same engine (seed {SEED}).\n")
    header = f"{'application':<26} {'native':>9} {'replayed':>9}  match"
    print(header)
    print("-" * len(header))
    agree = 0
    apps = available_apps()
    for name in apps:
        app = get_app(name)
        topo = _default_topology(app.roles())
        roles_to_nodes = {role: role for role in app.roles()}
        from qnetbench.backends.reference.backend import ReferenceBackend

        native = ReferenceBackend(topo, seed=SEED).run(app, {}, roles_to_nodes)
        backend = _RecordedBackend(topo, SEED, recorded_supplies(native))
        replayed = backend.run(app, {}, roles_to_nodes)
        nu, nr = outcome(native)
        ru, rr = outcome(replayed)
        same = (nu == ru) and (nr == rr)
        agree += same
        print(f"{name:<26} {nu:>9.6f} {ru:>9.6f}  {'yes' if same else 'NO'}")
    print(f"\n{agree}/{len(apps)} applications reproduce their native outcome exactly.")


if __name__ == "__main__":
    main()
