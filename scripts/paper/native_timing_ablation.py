"""What protocol timing does to a native NetSquid protocol, against qnetbench.

`native_netsquid.py` finds the native protocols and qnetbench's engine in agreement once the native code holds
qubits for as long as the applications do. Early on they disagreed, with identical physics, until two timing
details were matched. That first run was not saved, so this script recreates the disagreement on purpose: the same
cells and seeds, with each timing detail switched off in turn.

- teleport, "no hold": the sender prepares its data qubit at the moment the pair is delivered. The application
  prepares it one classical delay before generation starts, so it waits (delay + generation time) in memory.
- swap, "end node holds": the end node keeps its half in memory until the swap and measures then. The application
  measures it on delivery.

This is a reconstruction of the cause, not a replay of the first run's numbers. It shows how large a disagreement
each detail makes, in the cells where the matched code agrees.

    .venv-ns/bin/python scripts/paper/native_timing_ablation.py
"""

from __future__ import annotations

import math
import multiprocessing
import statistics
from pathlib import Path

import netsquid as ns
import numpy as np
from native_netsquid import (
    DELAY,
    NS,
    QUARTER,
    _channel,
    _memory,
    _native_cell,
    _pair,
    _qnetbench_cell,
    _Repeater,
    _ry,
    _SwapEnd,
    _TeleportReceiver,
    _TeleportSender,
)
from netsquid.nodes import Node
from netsquid.qubits import qubitapi as qapi

from qnetbench.characterize.provenance import write_atomic

OUT = Path(__file__).parent / "data" / "native_timing_ablation.txt"


class _TeleportSenderNoHold(_TeleportSender):
    """Prepares the data qubit when the pair is delivered, so it never waits in memory."""

    def run(self):
        yield self.await_timer(self.gen * NS)
        data = qapi.create_qubits(1)[0]
        qapi.operate(data, _ry(self.k * QUARTER))
        ours, theirs = _pair(self.fidelity, self.link)
        self.receiver.qmemory.put(theirs, positions=[0])
        qapi.operate([data, ours], ns.CNOT)
        qapi.operate(data, ns.H)
        m1, _ = qapi.measure(data)
        m2, _ = qapi.measure(ours)
        self.node.ports["cout"].tx_output((m1, m2))


class _RepeaterEndHolds(_Repeater):
    """Keeps the end node's half in memory until the swap, then measures it."""

    def run(self):
        yield self.await_timer(self.gens[0] * NS)
        ours_a, end_a = _pair(self.fidelity, self.link)
        self.node.qmemory.put([ours_a, end_a], positions=[0, 1])
        yield self.await_timer(self.gens[1] * NS)
        ours_b, end_b = _pair(self.fidelity, self.link)
        self.bob.qmemory.put(end_b, positions=[0])
        ours_a = self.node.qmemory.pop(0)[0]
        end_a = self.node.qmemory.pop(1)[0]
        self.alice_bit = qapi.measure(end_a, observable=ns.X if self.basis else ns.Z)[0]
        qapi.operate([ours_a, ours_b], ns.CNOT)
        qapi.operate(ours_a, ns.H)
        m1, _ = qapi.measure(ours_a)
        m2, _ = qapi.measure(ours_b)
        self.node.ports["cout"].tx_output((m1, m2))


def _teleport_no_hold(fidelity, t1, t2, link, rng) -> float:
    ns.sim_reset()
    ns.set_qstate_formalism(ns.QFormalism.DM)
    alice = Node("alice", qmemory=_memory("ma", 1, t1, t2))
    bob = Node("bob", qmemory=_memory("mb", 1, t1, t2))
    _channel(alice, "cout", bob, "cin")
    k = int(rng.integers(0, 8))
    gen = float(rng.exponential(DELAY))
    sender = _TeleportSenderNoHold(alice, gen, fidelity, link, k, bob)
    receiver = _TeleportReceiver(bob, k)
    receiver.start()
    sender.start()
    ns.sim_run()
    return float(receiver.result)


def _swap_end_holds(fidelity, t1, t2, link, basis, rng) -> int:
    ns.sim_reset()
    ns.set_qstate_formalism(ns.QFormalism.DM)
    bob = Node("bob", qmemory=_memory("mb", 1, t1, t2))
    repeater = Node("repeater", qmemory=_memory("mr", 2, t1, t2))
    _channel(repeater, "cout", bob, "cin")
    gens = (float(rng.exponential(DELAY)), float(rng.exponential(DELAY)))
    source = _RepeaterEndHolds(repeater, gens, fidelity, link, bob, basis)
    end = _SwapEnd(bob, source, basis)
    end.start()
    source.start()
    ns.sim_run()
    return end.result


def _variant_cell(args):
    kind, variant, fidelity, t2, seed, shots = args
    rng = np.random.default_rng(seed)
    ns.set_random_state(seed=seed)
    if kind == "teleport":
        return float(np.mean([_teleport_no_hold(fidelity, math.inf, t2, "werner", rng) for _ in range(shots)]))
    return float(np.mean([_swap_end_holds(fidelity, math.inf, t2, "werner", i % 2, rng) for i in range(shots)]))


def _summary(values: list[float]) -> tuple[float, float]:
    return statistics.fmean(values), statistics.stdev(values) / math.sqrt(len(values))


def main() -> None:
    seeds, shots = 32, 256
    rows = [
        "Native NetSquid timing ablation. 32 seeds of 256 rounds per cell, Werner links, dephasing memory.",
        "z is the difference from qnetbench over the combined standard error. 'matched' is native_netsquid.py.",
        "",
        f"   {'protocol':9}{'variant':16}{'F':>6}{'T2 (s)':>8}{'qnetbench':>18}{'native':>18}{'z':>8}",
    ]
    largest: dict[str, float] = {}
    with multiprocessing.Pool() as pool:
        for kind, variant in (
            ("teleport", "matched"),
            ("teleport", "no hold"),
            ("swap", "matched"),
            ("swap", "end node holds"),
        ):
            for fidelity in (0.85, 0.95, 0.99):
                for t2 in (0.05, 0.01):
                    ours = pool.map(_qnetbench_cell, [(kind, fidelity, t2, s, shots) for s in range(seeds)])
                    if variant == "matched":
                        theirs = pool.map(
                            _native_cell,
                            [(kind, fidelity, math.inf, t2, "werner", 10_000 + s, shots) for s in range(seeds)],
                        )
                    else:
                        theirs = pool.map(
                            _variant_cell,
                            [(kind, variant, fidelity, t2, 10_000 + s, shots) for s in range(seeds)],
                        )
                    m1, e1 = _summary(ours)
                    m2, e2 = _summary(theirs)
                    z = (m1 - m2) / math.hypot(e1, e2)
                    largest[f"{kind} {variant}"] = max(largest.get(f"{kind} {variant}", 0.0), abs(z))
                    rows.append(
                        f"   {kind:9}{variant:16}{fidelity:>6.2f}{t2:>8g}"
                        f"{f'{m1:.4f} ± {e1:.4f}':>18}{f'{m2:.4f} ± {e2:.4f}':>18}{z:>8.2f}"
                    )
    rows += ["", "Largest |z| per variant:"]
    rows += [f"   {name:24}{value:6.2f}" for name, value in largest.items()]
    text = "\n".join(rows) + "\n"
    write_atomic(OUT, text)
    print(text)


if __name__ == "__main__":
    main()
