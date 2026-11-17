"""Teleportation, BBM92 and swapping written directly on NetSquid, against qnetbench.

Replay shares only timing and fidelity with a simulator, so agreement across backends says nothing
about physics. These protocols use NetSquid's own event loop, qubit engine and memory noise
models, so they are an independent check on qnetbench's engine and held-qubit decay.

    A. Werner links and dephasing memory, which both can represent. They should agree.
    B. Links of equal fidelity but different noise, which qnetbench's engine cannot represent.
       The gap shows what assuming Werner pairs costs.
    C. Lines of code each way.

    .venv-ns/bin/python scripts/paper/native_netsquid.py
"""

from __future__ import annotations

import math
import multiprocessing
import statistics
from pathlib import Path

import netsquid as ns
import numpy as np
from netsquid.components import ClassicalChannel, QuantumMemory
from netsquid.components.models.qerrormodels import T1T2NoiseModel
from netsquid.nodes import Node
from netsquid.protocols import NodeProtocol
from netsquid.qubits import ketstates as ks
from netsquid.qubits import operators as ops
from netsquid.qubits import qubitapi as qapi

from qnetbench.apps import get_app
from qnetbench.backends.reference import ReferenceBackend
from qnetbench.characterize.provenance import write_atomic
from qnetbench.tenancy import ExecutionModel, TenantSpec, application_utility, run_tenants
from qnetbench.topology import LinkModel, default_topology
from qnetbench.trace.events import AppOutcomeEvent

OUT = Path(__file__).parent / "data" / "native_netsquid.txt"
DELAY = 1e-3  # classical delay and mean pair generation time, in seconds
NS = 1e9
QUARTER = math.pi / 4


# --- native protocols: everything from here to the marker is NetSquid only -----------------


def _memory(name: str, positions: int, t1: float, t2: float) -> QuantumMemory:
    model = T1T2NoiseModel(T1=0 if math.isinf(t1) else t1 * NS, T2=0 if math.isinf(t2) else t2 * NS)
    return QuantumMemory(name, num_positions=positions, memory_noise_models=[model] * positions)


def _pair(fidelity: float, link: str):
    """A Bell pair at `fidelity`, through one kind of noise on one arm."""
    a, b = qapi.create_qubits(2)
    qapi.assign_qstate([a, b], ks.b00)
    if link == "werner":
        qapi.depolarize(b, prob=4.0 * (1.0 - fidelity) / 3.0)
    elif link == "dephased":
        qapi.dephase(b, prob=1.0 - fidelity)
    elif link == "amplitude":
        qapi.amplitude_dampen(b, gamma=1.0 - (2.0 * math.sqrt(fidelity) - 1.0) ** 2, prob=1.0)
    else:
        raise ValueError(link)
    return a, b


def _channel(sender: Node, out: str, receiver: Node, into: str) -> None:
    sender.add_ports([out])
    receiver.add_ports([into])
    channel = ClassicalChannel(f"{sender.name}-{receiver.name}", delay=DELAY * NS)
    sender.ports[out].connect(channel.ports["send"])
    channel.ports["recv"].connect(receiver.ports[into])


def _ry(angle: float):
    return ops.create_rotation_op(angle, rotation_axis=(0, 1, 0))


class _TeleportSender(NodeProtocol):
    """Holds a data qubit while the pair is generated, then does a Bell measurement."""

    def __init__(self, node, gen, fidelity, link, k, receiver):
        super().__init__(node)
        self.gen, self.fidelity, self.link, self.k, self.receiver = gen, fidelity, link, k, receiver

    def run(self):
        data = qapi.create_qubits(1)[0]
        qapi.operate(data, _ry(self.k * QUARTER))
        self.node.qmemory.put(data, positions=[0])
        # As in apps/teleport.py: the sender prepares straight after its last send, and generation
        # starts once the receiver has finished that round, one classical delay later.
        yield self.await_timer((DELAY + self.gen) * NS)
        data = self.node.qmemory.pop(0)[0]
        ours, theirs = _pair(self.fidelity, self.link)
        self.receiver.qmemory.put(theirs, positions=[0])
        qapi.operate([data, ours], ns.CNOT)
        qapi.operate(data, ns.H)
        m1, _ = qapi.measure(data)
        m2, _ = qapi.measure(ours)
        self.node.ports["cout"].tx_output((m1, m2))


class _TeleportReceiver(NodeProtocol):
    def __init__(self, node, k):
        super().__init__(node)
        self.k = k
        self.result = None

    def run(self):
        yield self.await_port_input(self.node.ports["cin"])
        m1, m2 = self.node.ports["cin"].rx_input().items[0]
        qubit = self.node.qmemory.pop(0)[0]
        if m2:
            qapi.operate(qubit, ns.X)
        if m1:
            qapi.operate(qubit, ns.Z)
        qapi.operate(qubit, _ry(-self.k * QUARTER))
        self.result = qapi.fidelity(qubit, ks.s0, squared=True)


def native_teleport(fidelity, t1, t2, link, rng) -> float:
    ns.sim_reset()
    ns.set_qstate_formalism(ns.QFormalism.DM)
    alice = Node("alice", qmemory=_memory("ma", 1, t1, t2))
    bob = Node("bob", qmemory=_memory("mb", 1, t1, t2))
    _channel(alice, "cout", bob, "cin")
    k = int(rng.integers(0, 8))
    gen = float(rng.exponential(DELAY))
    sender = _TeleportSender(alice, gen, fidelity, link, k, bob)
    receiver = _TeleportReceiver(bob, k)
    receiver.start()
    sender.start()
    ns.sim_run()
    return float(receiver.result)


def native_bbm92(fidelity, link, rng) -> tuple[int, int]:
    """Both measure on delivery, as qkd does. Returns (matched basis, errors)."""
    ns.sim_reset()
    ns.set_qstate_formalism(ns.QFormalism.DM)
    a, b = _pair(fidelity, link)
    x_a, x_b = bool(rng.integers(0, 2)), bool(rng.integers(0, 2))
    if x_a != x_b:
        return 0, 0
    observable = ns.X if x_a else ns.Z
    bit_a, _ = qapi.measure(a, observable=observable)
    bit_b, _ = qapi.measure(b, observable=observable)
    return 1, int(bit_a != bit_b)


class _Repeater(NodeProtocol):
    """Waits for both pairs in turn, swaps them, and sends the correction."""

    def __init__(self, node, gens, fidelity, link, bob, basis):
        super().__init__(node)
        self.gens, self.fidelity, self.link = gens, fidelity, link
        self.bob, self.basis = bob, basis
        self.alice_bit = None

    def run(self):
        yield self.await_timer(self.gens[0] * NS)
        ours_a, end_a = _pair(self.fidelity, self.link)
        # As in apps/swap.py: the end node measures its half on delivery.
        self.alice_bit = qapi.measure(end_a, observable=ns.X if self.basis else ns.Z)[0]
        self.node.qmemory.put(ours_a, positions=[0])
        yield self.await_timer(self.gens[1] * NS)
        ours_b, end_b = _pair(self.fidelity, self.link)
        self.bob.qmemory.put(end_b, positions=[0])
        ours_a = self.node.qmemory.pop(0)[0]
        qapi.operate([ours_a, ours_b], ns.CNOT)
        qapi.operate(ours_a, ns.H)
        m1, _ = qapi.measure(ours_a)
        m2, _ = qapi.measure(ours_b)
        self.node.ports["cout"].tx_output((m1, m2))


class _SwapEnd(NodeProtocol):
    """Bob: holds his half until the correction lands, applies it, measures and compares."""

    def __init__(self, node, repeater, basis):
        super().__init__(node)
        self.repeater, self.basis = repeater, basis
        self.result = None

    def run(self):
        yield self.await_port_input(self.node.ports["cin"])
        m1, m2 = self.node.ports["cin"].rx_input().items[0]
        qubit = self.node.qmemory.pop(0)[0]
        if m2:
            qapi.operate(qubit, ns.X)
        if m1:
            qapi.operate(qubit, ns.Z)
        observable = ns.X if self.basis else ns.Z
        self.result = int(qapi.measure(qubit, observable=observable)[0] == self.repeater.alice_bit)


def native_swap(fidelity, t1, t2, link, basis, rng) -> int:
    ns.sim_reset()
    ns.set_qstate_formalism(ns.QFormalism.DM)
    bob = Node("bob", qmemory=_memory("mb", 1, t1, t2))
    repeater = Node("repeater", qmemory=_memory("mr", 1, t1, t2))
    _channel(repeater, "cout", bob, "cin")
    gens = (float(rng.exponential(DELAY)), float(rng.exponential(DELAY)))
    source = _Repeater(repeater, gens, fidelity, link, bob, basis)
    end = _SwapEnd(bob, source, basis)
    end.start()
    source.start()
    ns.sim_run()
    return end.result


# --- end of the native protocols ------------------------------------------------------------


def _native_cell(args):
    kind, fidelity, t1, t2, link, seed, shots = args
    rng = np.random.default_rng(seed)
    ns.set_random_state(seed=seed)
    if kind == "teleport":
        return float(np.mean([native_teleport(fidelity, t1, t2, link, rng) for _ in range(shots)]))
    if kind == "qber":
        results = [native_bbm92(fidelity, link, rng) for _ in range(shots)]
        matched = sum(m for m, _ in results)
        return sum(e for _, e in results) / matched
    if kind == "swap":
        return float(
            np.mean([native_swap(fidelity, t1, t2, link, i % 2, rng) for i in range(shots)])
        )
    raise ValueError(kind)


def _qnetbench_cell(args):
    kind, fidelity, t2, seed, shots = args
    link = LinkModel(DELAY, fidelity, 0.0)
    if kind == "teleport":
        run = run_tenants(
            [TenantSpec("t", "teleportation", {"rounds": shots})],
            seed=seed,
            link=link,
            coherence_time=t2,
            model=ExecutionModel(arrivals="closed_loop"),
        )
        return application_utility(run.traces["t"])
    if kind == "qber":
        run = run_tenants(
            [TenantSpec("t", "qkd", {"rounds": shots})],
            seed=seed,
            link=link,
            model=ExecutionModel(arrivals="closed_loop", aging="none"),
        )
        outcome = next(e for e in run.traces["t"] if isinstance(e, AppOutcomeEvent))
        return float(outcome.payload["qber"])
    if kind == "swap":
        app = get_app("entanglement_swap")
        roles = app.roles()
        backend = ReferenceBackend(default_topology(roles, link=link), seed=seed)
        if not math.isinf(t2):
            backend.enable_memory(t2, "dephasing")
        events = backend.run(app, {"rounds": shots}, {r: r for r in roles})
        return application_utility(events)
    raise ValueError(kind)


def _summary(values: list[float]) -> tuple[float, float]:
    return statistics.fmean(values), statistics.stdev(values) / math.sqrt(len(values))


def _source_lines() -> int:
    lines = Path(__file__).read_text().splitlines()
    start = next(i for i, x in enumerate(lines) if x.startswith("# --- native protocols"))
    end = next(i for i, x in enumerate(lines) if x.startswith("# --- end of the native"))
    body = [x for x in lines[start + 1 : end] if x.strip() and not x.strip().startswith("#")]
    return len(body)


def main() -> None:
    seeds = 32
    shots = 256
    inf = math.inf
    lines = [
        f"Native NetSquid against qnetbench. {seeds} seeds of {shots} rounds per cell, classical delay",
        f"and mean generation time {DELAY * 1e3:g} ms. z is the difference over its combined standard error.",
        "",
        "A. Werner links and dephasing memory, which both can represent",
        f"   {'protocol':12}{'F':>6}{'T2 (s)':>8}{'qnetbench':>18}{'NetSquid':>18}{'z':>7}",
    ]
    zs: list[float] = []
    with multiprocessing.Pool() as pool:
        for kind, label in (("teleport", "teleport"), ("swap", "swap"), ("qber", "BBM92 QBER")):
            memories = (inf,) if kind == "qber" else (inf, 0.05, 0.01)
            for fidelity in (0.85, 0.95, 0.99):
                for t2 in memories:
                    ours = pool.map(
                        _qnetbench_cell, [(kind, fidelity, t2, s, shots) for s in range(seeds)]
                    )
                    theirs = pool.map(
                        _native_cell,
                        [
                            (kind, fidelity, inf, t2, "werner", 10_000 + s, shots)
                            for s in range(seeds)
                        ],
                    )
                    m1, e1 = _summary(ours)
                    m2, e2 = _summary(theirs)
                    z = (m1 - m2) / math.hypot(e1, e2) if e1 or e2 else 0.0
                    zs.append(z)
                    lines.append(
                        f"   {label:12}{fidelity:>6.2f}{t2:>8g}{f'{m1:.4f} ± {e1:.4f}':>18}"
                        f"{f'{m2:.4f} ± {e2:.4f}':>18}{z:>7.2f}"
                    )
        within = sum(abs(z) <= 2 for z in zs)
        lines += [
            f"   {len(zs)} cells: {within} within 2 s.e., largest |z| {max(abs(z) for z in zs):.2f}.",
            "",
            "B. Links of equal fidelity with different noise, NetSquid only, no memory noise.",
            "   qnetbench's engine assumes Werner pairs, so its value matches the first column.",
            f"   {'quantity':14}{'F':>6}{'Werner':>10}{'dephased':>10}{'amplitude':>11}",
        ]
        for kind, label in (("teleport", "teleport"), ("swap", "swap"), ("qber", "BBM92 QBER")):
            for fidelity in (0.85, 0.95):
                cells = []
                for link in ("werner", "dephased", "amplitude"):
                    values = pool.map(
                        _native_cell,
                        [(kind, fidelity, inf, inf, link, 20_000 + s, shots) for s in range(seeds)],
                    )
                    cells.append(statistics.fmean(values))
                lines.append(
                    f"   {label:14}{fidelity:>6.2f}{cells[0]:>10.4f}{cells[1]:>10.4f}{cells[2]:>11.4f}"
                )
        lines += [
            "",
            "C. Memory noise with amplitude damping, against qnetbench's dephasing at the same T2.",
            f"   {'protocol':12}{'F':>6}{'T1=T2 (s)':>10}{'NetSquid T1=T2':>17}{'qnetbench T2 only':>20}",
        ]
        for kind, label in (("teleport", "teleport"), ("swap", "swap")):
            for t in (0.05, 0.01):
                theirs = pool.map(
                    _native_cell,
                    [(kind, 0.95, t, t, "werner", 30_000 + s, shots) for s in range(seeds)],
                )
                ours = pool.map(_qnetbench_cell, [(kind, 0.95, t, s, shots) for s in range(seeds)])
                lines.append(
                    f"   {label:12}{0.95:>6.2f}{t:>10g}"
                    f"{statistics.fmean(theirs):>17.4f}{statistics.fmean(ours):>20.4f}"
                )
    lines += [
        "",
        f"D. The three native protocols and their helpers take {_source_lines()} lines of code in this",
        "   file, for one simulator. In qnetbench each is one TenantSpec, and runs on all three supplies.",
    ]
    text = "\n".join(lines) + "\n"
    write_atomic(OUT, text)
    print(text)


if __name__ == "__main__":
    main()
