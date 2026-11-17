"""What a protocol written directly on SeQUeNCe would see, against what qnetbench's engine sees.

qnetbench replays only the timing and the delivered fidelity of a SeQUeNCe supply, on the grounds that
a simulator's device noise does not act on application qubits. This script checks that natively. It runs
the same two-router reservation as `qnetbench/backends/sequence/supply.py`, and at the moment each pair is
delivered it reads the quantum state SeQUeNCe actually holds for that pair from its own quantum manager.

For each raw memory fidelity it reports:

- the fidelity SeQUeNCe labels the pair with;
- the overlap of the stored state with the nearest Bell state;
- the BBM92 error rate that state would give, 2 (1 - overlap) / 3 for a Werner pair, against what a Werner pair at
  the labelled fidelity gives, 2 (1 - label) / 3, which is what qnetbench's engine and NetSquid report.

    .venv/bin/python scripts/paper/native_sequence.py
"""

from __future__ import annotations

import itertools
import multiprocessing
import statistics
from importlib.metadata import version
from pathlib import Path

import numpy as np
from sequence.app.request_app import RequestApp
from sequence.resource_management.memory_manager import MemoryInfo
from sequence.topology.router_net_topo import RouterNetTopo

from qnetbench.characterize.provenance import write_atomic

OUT = Path(__file__).parent / "data" / "native_sequence.txt"
FIDELITIES = (0.99, 0.95, 0.85, 0.7, 0.6)
SEEDS = 8
CC_DELAY_PS = 1e9  # 1 ms classical delay
START_PS = 5e10
WINDOW_PS = 2e11
S2 = 2 ** -0.5
BELLS = {
    "phi+": np.array([S2, 0, 0, S2]),
    "phi-": np.array([S2, 0, 0, -S2]),
    "psi+": np.array([0, S2, S2, 0]),
    "psi-": np.array([0, S2, -S2, 0]),
}


def _overlap(state: np.ndarray) -> tuple[float, str]:
    """Largest overlap of the stored two-qubit state with a Bell state, and which one."""
    state = np.asarray(state)
    if state.ndim == 1:
        weights = {name: abs(np.vdot(vec, state)) ** 2 for name, vec in BELLS.items()}
    else:
        weights = {name: float(np.real(np.vdot(vec, state @ vec))) for name, vec in BELLS.items()}
    name = max(weights, key=weights.get)
    return weights[name], name


def _run(args: tuple[float, int]) -> list[tuple[float, float, str]]:
    fidelity, seed = args
    config = {
        "stop_time": (START_PS + WINDOW_PS) * 1.1,
        "nodes": [
            {"name": "alice", "type": "QuantumRouter", "seed": seed, "memo_size": 2},
            {"name": "bob", "type": "QuantumRouter", "seed": seed + 1, "memo_size": 2},
        ],
        "qconnections": [
            {"node1": "alice", "node2": "bob", "attenuation": 0.0, "distance": 1000.0, "type": "meet_in_the_middle"}
        ],
        "cconnections": [{"node1": "alice", "node2": "bob", "delay": CC_DELAY_PS}],
    }
    topo = RouterNetTopo(config)
    timeline = topo.get_timeline()
    routers = {n.name: n for n in topo.get_nodes_by_type(RouterNetTopo.QUANTUM_ROUTER)}
    for node in routers.values():
        memories = node.components[node.memo_arr_name]
        memories.update_memory_params("coherence_time", -1)
        memories.update_memory_params("raw_fidelity", fidelity)

    seen: list[tuple[float, float, str]] = []

    class _Reader(RequestApp):  # type: ignore[misc]
        def get_memory(self, info: object) -> None:
            assert isinstance(info, MemoryInfo)
            if info.state == MemoryInfo.ENTANGLED and info.index in self.memo_to_reservation:
                reservation = self.memo_to_reservation[info.index]
                if info.remote_node == reservation.responder and info.fidelity >= reservation.fidelity:
                    memory = self.node.components[self.node.memo_arr_name][info.index]
                    stored = timeline.quantum_manager.get(memory.qstate_key)
                    overlap, name = _overlap(stored.state)
                    seen.append((info.fidelity, overlap, name))
            super().get_memory(info)

    alice = _Reader(routers["alice"])
    _Reader(routers["bob"])
    timeline.init()
    alice.start("bob", int(START_PS), int(START_PS + WINDOW_PS), 2, 0.5)
    timeline.run()
    return seen


def main() -> None:
    lines = [
        "Native SeQUeNCe: the state held for each delivered pair, against its fidelity label.",
        f"SeQUeNCe {version('sequence')}, default quantum manager. Two routers 1 km apart, 1 ms classical delay,",
        f"decoherence disabled, {SEEDS} seeds per row.",
        "QBER is for BBM92 on a Werner pair, 2 (1 - F) / 3. 'implied' uses the stored state's Bell overlap;",
        "'labelled' uses the fidelity SeQUeNCe reports, which is what qnetbench and NetSquid use.",
        "",
        f"{'raw F':>6}{'pairs':>7}{'label':>8}{'Bell overlap':>14}{'Bell state':>12}{'QBER implied':>14}{'QBER labelled':>15}",
    ]
    with multiprocessing.Pool() as pool:
        for fidelity in FIDELITIES:
            runs = pool.map(_run, [(fidelity, seed) for seed in range(SEEDS)])
            pairs = list(itertools.chain.from_iterable(runs))
            label = statistics.fmean(p[0] for p in pairs)
            overlap = statistics.fmean(p[1] for p in pairs)
            names = sorted({p[2] for p in pairs})
            lines.append(
                f"{fidelity:>6.2f}{len(pairs):>7}{label:>8.3f}{overlap:>14.4f}{'/'.join(names):>12}"
                f"{max(0.0, 2 * (1 - overlap) / 3):>14.4f}{2 * (1 - label) / 3:>15.4f}"
            )
    lines += [
        "",
        "SeQUeNCe's delivered pair is a pure Bell state whatever fidelity it reports. A protocol written natively",
        "on it sees a perfect pair unless the author applies the noise by hand, so the fidelity label is the only",
        "channel through which its link physics reaches an application. That is the channel qnetbench replays.",
    ]
    text = "\n".join(lines) + "\n"
    write_atomic(OUT, text)
    print(text)


if __name__ == "__main__":
    main()
