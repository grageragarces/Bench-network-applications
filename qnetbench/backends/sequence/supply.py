"""Extract an entanglement *supply* from a SeQUeNCe simulation.

The hybrid SeQUeNCe backend lets SeQUeNCe own the entanglement-generation physics
— delivery timing and delivered fidelity between two routers — and replays that
supply into qnetbench's execution engine (which runs the local quantum ops and the
classical protocol). This module runs a SeQUeNCe reservation between two
QuantumRouters and records the ordered stream of delivered pairs.

Requires the optional `sequence` extra: ``pip install qnetbench[sequence]``.
"""

from __future__ import annotations

from qnetbench.backends.replay import Supply


def generate_supply(
    *,
    seed: int,
    window_s: float,
    link_fidelity: float,
    classical_latency_s: float,
    target_fidelity: float = 0.5,
    distance_m: float = 1000.0,
    attenuation: float = 0.0,
    memo_size: int = 50,
) -> Supply:
    """Run a two-router SeQUeNCe simulation and return its delivered-pair stream.

    `link_fidelity` sets the raw memory fidelity (delivered fidelity ≈ this, with
    decoherence disabled); `window_s` is the reservation length in seconds.
    """
    from sequence.app.request_app import RequestApp
    from sequence.resource_management.memory_manager import MemoryInfo
    from sequence.topology.router_net_topo import RouterNetTopo

    window_ps = window_s * 1e12
    cc_delay_ps = classical_latency_s * 1e12
    # The reservation must start after the RSVP round-trip completes; a generous
    # fixed offset covers the classical handshake before the generation window.
    start_ps = max(5e10, cc_delay_ps * 20.0)

    config = {
        "stop_time": (start_ps + window_ps) * 1.1,
        "nodes": [
            {"name": "alice", "type": "QuantumRouter", "seed": seed, "memo_size": memo_size},
            {"name": "bob", "type": "QuantumRouter", "seed": seed + 1, "memo_size": memo_size},
        ],
        "qconnections": [
            {
                "node1": "alice",
                "node2": "bob",
                "attenuation": attenuation,
                "distance": distance_m,
                "type": "meet_in_the_middle",
            }
        ],
        "cconnections": [{"node1": "alice", "node2": "bob", "delay": cc_delay_ps}],
    }

    topo = RouterNetTopo(config)
    tl = topo.get_timeline()
    routers = {n.name: n for n in topo.get_nodes_by_type(RouterNetTopo.QUANTUM_ROUTER)}
    for node in routers.values():
        marr = node.components[node.memo_arr_name]
        marr.update_memory_params("coherence_time", -1)  # disable decoherence
        marr.update_memory_params("raw_fidelity", link_fidelity)  # sets delivered fidelity

    deliveries: list[tuple[float, float]] = []

    class _RecordingApp(RequestApp):  # type: ignore[misc]
        def get_memory(self, info: object) -> None:
            assert isinstance(info, MemoryInfo)
            if info.state == MemoryInfo.ENTANGLED and info.index in self.memo_to_reservation:
                res = self.memo_to_reservation[info.index]
                if info.remote_node == res.responder and info.fidelity >= res.fidelity:
                    deliveries.append((self.node.timeline.now(), info.fidelity))
            super().get_memory(info)

    alice = _RecordingApp(routers["alice"])
    _RecordingApp(routers["bob"])

    tl.init()
    alice.start("bob", int(start_ps), int(start_ps + window_ps), memo_size, target_fidelity)
    tl.run()

    deliveries.sort(key=lambda d: d[0])
    inter_arrivals: list[float] = []
    prev = start_ps
    for t_ps, _ in deliveries:
        inter_arrivals.append((t_ps - prev) / 1e12)
        prev = t_ps
    fidelities = [f for _, f in deliveries]
    return Supply(
        inter_arrivals=inter_arrivals,
        fidelities=fidelities,
        classical_latency=classical_latency_s,
    )
