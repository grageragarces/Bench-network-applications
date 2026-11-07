"""Extract an entanglement *supply* from a NetSquid simulation.

An elementary link is modelled with NetSquid's discrete-event engine: a `QSource`
on an internal clock emits Bell pairs at `frequency`, each half travelling a fibre
`QuantumChannel` (fixed delay for timing), with a depolarising noise model on one
arm tuned to the target fidelity. The delivered (arrival-time, fidelity) stream is
collected and returned for replay.

Requires the optional `netsquid` extra (installed from https://pypi.netsquid.org).
"""

from __future__ import annotations

from qnetbench.backends.replay import Supply


def generate_supply(
    *,
    seed: int,
    window_s: float,
    link_fidelity: float,
    classical_latency_s: float,
    frequency: float = 2000.0,
    channel_delay_s: float | None = None,
    timing: str = "fixed",
) -> Supply:
    """Run a NetSquid elementary-link simulation and return its delivered-pair stream.

    `frequency` is the source emission rate (Hz); `link_fidelity` is the delivered
    fidelity (via a depolarising channel); `window_s` is the run length in seconds.
    `timing` is "fixed" for a pair every period, or "exponential" for random gaps with that mean,
    which is how a heralded link with a small success probability per attempt behaves.
    """
    import netsquid as ns
    import netsquid.qubits.ketstates as ks
    from netsquid.components.models.delaymodels import DelayModel, FixedDelayModel
    from netsquid.components.models.qerrormodels import DepolarNoiseModel
    from netsquid.components.qchannel import QuantumChannel
    from netsquid.components.qsource import QSource, SourceStatus
    from netsquid.qubits import qubitapi as qapi
    from netsquid.qubits.state_sampler import StateSampler
    from netsquid.util.simtools import get_random_state

    class ExponentialDelayModel(DelayModel):  # type: ignore[misc]
        def __init__(self, mean_ns: float) -> None:
            super().__init__()
            self.mean_ns = mean_ns

        def generate_delay(self, **kwargs: object) -> float:
            return float(get_random_state().exponential(self.mean_ns))

    if timing not in ("fixed", "exponential"):
        raise ValueError(f"timing must be 'fixed' or 'exponential', got {timing!r}")

    ns.sim_reset()
    ns.set_qstate_formalism(ns.QFormalism.DM)
    ns.set_random_state(seed=seed)

    period_ns = 1e9 / frequency
    delay_ns = (channel_delay_s if channel_delay_s is not None else classical_latency_s) * 1e9
    # Depolarising one half of a Bell pair by p gives fidelity F = 1 - 3p/4.
    depolar_p = min(1.0, max(0.0, 4.0 * (1.0 - link_fidelity) / 3.0))

    sampler = StateSampler([ks.b00], [1.0])
    source = QSource(
        "qsource",
        state_sampler=sampler,
        num_ports=2,
        status=SourceStatus.INTERNAL,
        timing_model=(
            FixedDelayModel(delay=period_ns)
            if timing == "fixed"
            else ExponentialDelayModel(period_ns)
        ),
    )

    deliveries: list[tuple[float, float]] = []
    buffer: dict[float, dict[int, object]] = {}

    def make_handler(idx: int):  # type: ignore[no-untyped-def]
        def handle(message: object) -> None:
            t = ns.sim_time()
            qubit = message.items[0]  # type: ignore[attr-defined]
            buffer.setdefault(t, {})[idx] = qubit
            if len(buffer[t]) == 2:
                pair = buffer.pop(t)
                fidelity = qapi.fidelity([pair[0], pair[1]], ks.b00, squared=True)
                deliveries.append((t, float(fidelity)))

        return handle

    for i in (0, 1):
        models = {}
        if i == 0 and depolar_p > 0:
            models["quantum_noise_model"] = DepolarNoiseModel(
                depolar_rate=depolar_p, time_independent=True
            )
        channel = QuantumChannel(f"channel{i}", delay=delay_ns, models=models)
        source.ports[f"qout{i}"].connect(channel.ports["send"])
        channel.ports["recv"].bind_output_handler(make_handler(i))

    ns.sim_run(duration=window_s * 1e9)

    deliveries.sort(key=lambda d: d[0])
    inter_arrivals: list[float] = []
    prev = 0.0
    for t_ns, _ in deliveries:
        inter_arrivals.append((t_ns - prev) / 1e9)
        prev = t_ns
    fidelities = [f for _, f in deliveries]
    return Supply(
        inter_arrivals=inter_arrivals,
        fidelities=fidelities,
        classical_latency=classical_latency_s,
    )
