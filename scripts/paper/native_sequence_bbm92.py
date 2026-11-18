"""BBM92 written directly on SeQUeNCe, against qnetbench's engine on the same link description.

`native_netsquid.py` writes three protocols natively on NetSquid. This is the matching check on SeQUeNCe, for the one
protocol whose result is a plain error rate. The protocol uses SeQUeNCe's own router reservation to generate pairs
and its own quantum manager to measure them: each end picks a basis at random, the rounds where the bases agree are
kept, and the error rate is the fraction of kept rounds whose outcomes break the correlation a Bell pair should show.

In its default ket-vector formalism SeQUeNCe stores a pure Bell state for each delivered pair, drawing the wrong
Bell state with probability 1 - F, so over many pairs a native protocol sees a Werner pair at the reported fidelity
(`native_sequence.py`). qnetbench replays the reported fidelity into its own engine. The columns below show what each
gives at the same link fidelity, against the closed form.

    .venv/bin/python scripts/paper/native_sequence_bbm92.py
"""

from __future__ import annotations

import multiprocessing
import statistics
from importlib.metadata import version
from pathlib import Path

import numpy as np

from qnetbench.characterize.provenance import write_atomic
from qnetbench.tenancy import ExecutionModel, TenantSpec, run_tenants
from qnetbench.topology import LinkModel
from qnetbench.trace.events import AppOutcomeEvent

OUT = Path(__file__).parent / "data" / "native_sequence_bbm92.txt"
FIDELITIES = (0.99, 0.95, 0.85, 0.7, 0.6)
SEEDS = 32
SHOTS = 256
CC_DELAY_PS = 1e9  # 1 ms classical delay
START_PS = 5e10
WINDOW_PS = 2e11


# --- native protocol: everything from here to the marker is SeQUeNCe only ------------------


def native_bbm92(fidelity: float, seed: int) -> tuple[int, int]:
    """Returns (rounds kept after sifting, rounds whose outcomes broke the correlation)."""
    from sequence.app.request_app import RequestApp
    from sequence.components.circuit import Circuit
    from sequence.resource_management.memory_manager import MemoryInfo
    from sequence.topology.router_net_topo import RouterNetTopo

    config = {
        "stop_time": (START_PS + WINDOW_PS) * 1.1,
        "nodes": [
            {"name": "alice", "type": "QuantumRouter", "seed": seed, "memo_size": 2},
            {"name": "bob", "type": "QuantumRouter", "seed": seed + 1, "memo_size": 2},
        ],
        "qconnections": [
            {
                "node1": "alice",
                "node2": "bob",
                "attenuation": 0.0,
                "distance": 1000.0,
                "type": "meet_in_the_middle",
                "seed": seed + 2,  # the BSM node's seed; SeQUeNCe defaults it to 0 for every run
            }
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
        # The BSM builds the stored state from each memory's photon encoding, which copied
        # raw_fidelity when the memory was made (default 0.85), so it is updated as well.
        for memory in memories.memories:
            memory.encoding["raw_fidelity"] = fidelity
    rng = np.random.default_rng(seed)
    tally = [0, 0]

    class _Bbm92(RequestApp):  # type: ignore[misc]
        def get_memory(self, info: object) -> None:
            assert isinstance(info, MemoryInfo)
            if info.state == MemoryInfo.ENTANGLED and info.index in self.memo_to_reservation:
                reservation = self.memo_to_reservation[info.index]
                if info.remote_node == reservation.responder and info.fidelity >= reservation.fidelity:
                    memory = self.node.components[self.node.memo_arr_name][info.index]
                    keys = timeline.quantum_manager.get(memory.qstate_key).keys
                    basis_a, basis_b = rng.integers(0, 2, size=2)
                    if basis_a == basis_b:
                        circuit = Circuit(2)
                        if basis_a:
                            circuit.h(0)
                            circuit.h(1)
                        circuit.measure(0)
                        circuit.measure(1)
                        bits = timeline.quantum_manager.run_circuit(circuit, keys, float(rng.random()))
                        a, b = (bits[k] for k in keys)
                        # SeQUeNCe delivers psi+: Z outcomes differ, X outcomes agree.
                        broken = (a == b) if basis_a == 0 else (a != b)
                        tally[0] += 1
                        tally[1] += int(broken)
            super().get_memory(info)

    alice = _Bbm92(routers["alice"])
    _Bbm92(routers["bob"])
    timeline.init()
    alice.start("bob", int(START_PS), int(START_PS + WINDOW_PS), 2, 0.5)
    timeline.run()
    return tally[0], tally[1]


# --- end of the native protocol --------------------------------------------------------------


def _source_lines() -> int:
    lines = Path(__file__).read_text().splitlines()
    start = next(i for i, x in enumerate(lines) if x.startswith("# --- native protocol"))
    end = next(i for i, x in enumerate(lines) if x.startswith("# --- end of the native"))
    body = [x for x in lines[start + 1 : end] if x.strip() and not x.strip().startswith("#")]
    return len(body)


def _native(args: tuple[float, int]) -> tuple[int, int]:
    return native_bbm92(*args)


def _qnetbench(args: tuple[float, int]) -> float:
    fidelity, seed = args
    run = run_tenants(
        [TenantSpec("t", "qkd", {"rounds": SHOTS})],
        seed=seed,
        link=LinkModel(1e-3, fidelity, 0.0),
        model=ExecutionModel(arrivals="closed_loop", aging="none"),
    )
    outcome = next(e for e in run.traces["t"] if isinstance(e, AppOutcomeEvent))
    return float(outcome.payload["qber"])


def main() -> None:
    lines = [
        f"BBM92 written directly on SeQUeNCe {version('sequence')}, against qnetbench's engine at the same link fidelity.",
        f"Two routers 1 km apart, 1 ms classical delay, decoherence disabled, {SEEDS} seeds per row.",
        "QBER = rounds breaking the Bell-pair correlation / rounds kept after sifting. The closed form for a Werner",
        "pair at fidelity F is 2 (1 - F) / 3.",
        "",
        f"{'F':>6}{'kept':>7}{'broken':>8}{'native SeQUeNCe':>17}{'qnetbench':>12}{'closed form':>13}",
    ]
    with multiprocessing.Pool() as pool:
        for fidelity in FIDELITIES:
            native = pool.map(_native, [(fidelity, s) for s in range(SEEDS)])
            engine = pool.map(_qnetbench, [(fidelity, s) for s in range(SEEDS)])
            kept = sum(k for k, _ in native)
            broken = sum(b for _, b in native)
            lines.append(
                f"{fidelity:>6.2f}{kept:>7}{broken:>8}{broken / kept:>17.4f}"
                f"{statistics.fmean(engine):>12.4f}{2 * (1 - fidelity) / 3:>13.4f}"
            )
    lines += [
        "",
        f"The native protocol, including the SeQUeNCe reservation that generates the pairs, takes {_source_lines()} lines",
        "of code. In qnetbench the same experiment is one TenantSpec, and it runs on all three supplies.",
    ]
    text = "\n".join(lines) + "\n"
    write_atomic(OUT, text)
    print(text)


if __name__ == "__main__":
    main()
