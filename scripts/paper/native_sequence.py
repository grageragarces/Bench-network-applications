"""What a protocol written directly on SeQUeNCe would see, against what qnetbench's engine sees.

qnetbench replays only the timing and the delivered fidelity of a SeQUeNCe supply, on the grounds that
a simulator's device noise does not act on application qubits. This script checks that natively. It runs
the same two-router reservation as `qnetbench/backends/sequence/supply.py`, and at the moment each pair is
delivered it reads the quantum state SeQUeNCe actually holds for that pair from its own quantum manager.

For each raw memory fidelity it reports:

- the fidelity SeQUeNCe labels the pair with;
- the overlap of the stored state with psi+, the Bell state generation heralds;
- the BBM92 error rate that state would give, 2 (1 - overlap) / 3 for a Werner pair, against what a Werner pair at
  the labelled fidelity gives, 2 (1 - label) / 3, which is what qnetbench's engine and NetSquid report.

It does so under the two formalisms SeQUeNCe's default Barrett-Kok generation runs in, the ket vector
(SeQUeNCe's default) and the density matrix. The Bell-diagonal formalism needs single-heralded generation
instead, which in this two-router configuration delivered no pairs, so it is not included.

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
from sequence.entanglement_management.generation import EntanglementGenerationA
from sequence.resource_management.memory_manager import MemoryInfo
from sequence.topology.router_net_topo import RouterNetTopo

from qnetbench.characterize.provenance import write_atomic

OUT = Path(__file__).parent / "data" / "native_sequence.txt"
FIDELITIES = (0.99, 0.95, 0.85, 0.7, 0.6)
# (formalism, generation protocol). Barrett-Kok is SeQUeNCe's default protocol.
FORMALISMS = (
    ("ket_vector", "barret_kok"),
    ("density_matrix", "barret_kok"),
)
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


def _overlap(state: np.ndarray, formalism: str) -> tuple[float, str]:
    """Overlap of the stored two-qubit state with the intended Bell state, psi+, and the nearest one.

    Barrett-Kok generation heralds psi+ once the end nodes have corrected. In the ket-vector formalism
    each pair is some pure Bell state, so the overlap is 1 or 0 per pair and its mean over pairs is the
    fidelity of the ensemble; in the density-matrix formalism it is the fidelity of each pair.
    """
    state = np.asarray(state)
    if state.ndim == 1:
        weights = {name: abs(np.vdot(vec, state)) ** 2 for name, vec in BELLS.items()}
    else:
        weights = {name: float(np.real(np.vdot(vec, state @ vec))) for name, vec in BELLS.items()}
    return float(weights["psi+"]), max(weights, key=weights.get)


def _run(args: tuple[str, str, float, int]) -> list[tuple[float, float, str]]:
    formalism, generation, fidelity, seed = args
    # A class-level setting in SeQUeNCe, so it is set on every run in case a worker ran another.
    EntanglementGenerationA.set_global_type(generation)
    connection: dict[str, object] = {
        "node1": "alice",
        "node2": "bob",
        "attenuation": 0.0,
        "distance": 1000.0,
        "type": "meet_in_the_middle",
        "seed": seed + 2,  # the BSM node's seed; SeQUeNCe defaults it to 0 for every run
    }
    templates: dict[str, object] = {}
    if generation == "single_heralded":
        templates["heralded"] = {"encoding_type": "single_heralded"}
        connection["template"] = "heralded"
    config = {
        "formalism": formalism,
        "templates": templates,
        "stop_time": (START_PS + WINDOW_PS) * 1.1,
        "nodes": [
            {"name": "alice", "type": "QuantumRouter", "seed": seed, "memo_size": 2},
            {"name": "bob", "type": "QuantumRouter", "seed": seed + 1, "memo_size": 2},
        ],
        "qconnections": [connection],
        "cconnections": [{"node1": "alice", "node2": "bob", "delay": CC_DELAY_PS}],
    }
    topo = RouterNetTopo(config)
    timeline = topo.get_timeline()
    routers = {n.name: n for n in topo.get_nodes_by_type(RouterNetTopo.QUANTUM_ROUTER)}
    for node in routers.values():
        memories = node.components[node.memo_arr_name]
        memories.update_memory_params("coherence_time", -1)
        memories.update_memory_params("raw_fidelity", fidelity)
        # The BSM builds the stored state from each memory's photon encoding, which copied raw_fidelity
        # when the memory was made (default 0.85). Setting raw_fidelity afterwards changes only the
        # label, so the encoding is updated too, or the density-matrix state would stay at 0.85.
        for memory in memories.memories:
            memory.encoding["raw_fidelity"] = fidelity

    seen: list[tuple[float, float, str]] = []

    class _Reader(RequestApp):  # type: ignore[misc]
        def get_memory(self, info: object) -> None:
            assert isinstance(info, MemoryInfo)
            if info.state == MemoryInfo.ENTANGLED and info.index in self.memo_to_reservation:
                reservation = self.memo_to_reservation[info.index]
                if info.remote_node == reservation.responder and info.fidelity >= reservation.fidelity:
                    memory = self.node.components[self.node.memo_arr_name][info.index]
                    stored = timeline.quantum_manager.get(memory.qstate_key)
                    overlap, name = _overlap(stored.state, formalism)
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
        f"SeQUeNCe {version('sequence')}, Barrett-Kok generation. Two routers 1 km apart, 1 ms classical "
        "delay,",
        f"decoherence disabled, {SEEDS} seeds per row.",
        "'overlap' is the mean overlap of the stored state with psi+, the state generation heralds.",
        "'other' is the fraction of pairs whose nearest Bell state is not psi+.",
        "QBER is for BBM92, 2 (1 - F) / 3: 'implied' from the overlap, 'labelled' from the reported fidelity,",
        "which is what qnetbench replays.",
    ]
    with multiprocessing.Pool() as pool:
        for formalism, generation in FORMALISMS:
            lines += [
                "",
                f"Formalism: {formalism}" + (" (SeQUeNCe's default)" if formalism == "ket_vector" else ""),
                f"{'raw F':>6}{'pairs':>7}{'label':>8}{'overlap':>10}{'other':>8}"
                f"{'QBER implied':>14}{'QBER labelled':>15}",
            ]
            for fidelity in FIDELITIES:
                work = [(formalism, generation, fidelity, seed) for seed in range(SEEDS)]
                pairs = list(itertools.chain.from_iterable(pool.map(_run, work)))
                label = statistics.fmean(p[0] for p in pairs)
                overlap = statistics.fmean(p[1] for p in pairs)
                other = sum(p[2] != "psi+" for p in pairs) / len(pairs)
                lines.append(
                    f"{fidelity:>6.2f}{len(pairs):>7}{label:>8.3f}{overlap:>10.4f}{other:>8.3f}"
                    f"{max(0.0, 2 * (1 - overlap) / 3):>14.4f}{2 * (1 - label) / 3:>15.4f}"
                )
    lines += [
        "",
        "In the ket-vector formalism each delivered pair is a pure Bell state, psi+ with probability F and",
        "one of the other three otherwise, so over many pairs a native protocol sees a Werner state at the",
        "reported fidelity. In the density-matrix formalism each pair is that Werner state. Both carry the",
        "fidelity qnetbench replays, provided it is set before the memories are made or their photon",
        "encoding is updated with it: setting raw_fidelity afterwards changes only the label.",
    ]
    text = "\n".join(lines) + "\n"
    write_atomic(OUT, text)
    print(text)

if __name__ == "__main__":
    main()
