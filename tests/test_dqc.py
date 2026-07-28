"""DQC circuit-demand benchmarks and the distributed-circuit IR."""

from __future__ import annotations

import pytest

from qnetbench.circuits import (
    Circuit,
    Op,
    from_qiskit,
    ghz,
    inverse_op,
    mirror,
    qft,
    random_circuit,
)
from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, line2
from qnetbench.trace.events import EntanglementRequested

PERFECT = line2(link=LinkModel(link_fidelity=1.0, fidelity_std=0.0))
DQC_APPS = ["dqc_ghz4", "dqc_qft4", "dqc_random4"]


# --- circuit IR ---------------------------------------------------------------


def test_inverse_of_self_inverse_and_rotation() -> None:
    assert inverse_op(Op("CNOT", (0, 1))) == Op("CNOT", (0, 1))
    assert inverse_op(Op("RZ", (0,), (0.5,))) == Op("RZ", (0,), (-0.5,))


def test_mirror_doubles_and_reverses() -> None:
    fwd = [Op("H", (0,)), Op("CNOT", (0, 1))]
    m = mirror(fwd)
    assert len(m) == 4
    assert m[2:] == [Op("CNOT", (0, 1)), Op("H", (0,))]  # reversed + inverted


def test_nonlocal_detection_and_layers() -> None:
    c = Circuit(2, (0, 1), [Op("H", (0,)), Op("CNOT", (0, 1))])
    assert not c.is_nonlocal(c.ops[0])
    assert c.is_nonlocal(c.ops[1])  # qubit 0 on node 0, qubit 1 on node 1
    assert c.layers() == [1, 2]  # H then the CNOT one layer later
    assert c.n_nonlocal() == 1


def test_library_circuits_are_nonlocal() -> None:
    for circuit in (ghz(4), qft(4), random_circuit(4, depth=6, seed=0)):
        assert circuit.n_nonlocal() > 0  # every library circuit induces entanglement demand


# --- executor -----------------------------------------------------------------


@pytest.mark.parametrize("app", DQC_APPS)
def test_mirror_circuits_return_all_zero_noiseless(app: str) -> None:
    assert _report(app).app_utility == 1.0  # U;U† returns |0…0>, every qubit reads 0


@pytest.mark.parametrize("app", DQC_APPS)
def test_demand_schedule_matches_nonlocal_gate_count(app: str) -> None:
    from qnetbench.apps import get_app

    events = run_once(app, seed=0)
    requests = sum(1 for e in events if isinstance(e, EntanglementRequested))
    circuit = get_app(app).circuit  # type: ignore[attr-defined]
    assert requests == circuit.n_nonlocal()  # one teleported gate per non-local gate


def test_utility_degrades_with_fidelity() -> None:
    def mean(app: str, fidelity: float) -> float:
        topo = line2(link=LinkModel(link_fidelity=fidelity, fidelity_std=0.0))
        return sum(_report(app, s, topo).app_utility for s in range(6)) / 6

    # QFT has the most teleported gates, so it degrades fastest.
    assert mean("dqc_qft4", 1.0) >= mean("dqc_qft4", 0.9) >= mean("dqc_qft4", 0.8)
    assert mean("dqc_qft4", 0.9) < mean("dqc_ghz4", 0.9)


def _report(app: str, seed: int = 0, topo=PERFECT):
    return compute_report(run_once(app, seed=seed, topology=topo))


# --- optional Qiskit / MQT Bench loader ---------------------------------------


# A minimal duck-typed stand-in for a Qiskit QuantumCircuit, so the loader is
# covered without the optional dependency installed.
class _FakeOp:
    def __init__(self, name: str, params: tuple[float, ...] = ()) -> None:
        self.name, self.params = name, params


class _FakeInstr:
    def __init__(self, name: str, qubits: tuple[int, ...], params: tuple[float, ...] = ()) -> None:
        self.operation = _FakeOp(name, params)
        self.qubits = qubits


class _FakeQC:
    def __init__(self, num_qubits: int, data: list[_FakeInstr]) -> None:
        self.num_qubits = num_qubits
        self.data = data

    def find_bit(self, q: int) -> object:
        return type("Bit", (), {"index": q})()


def test_from_qiskit_converts_supported_gates() -> None:
    qc = _FakeQC(
        2, [_FakeInstr("h", (0,)), _FakeInstr("cx", (0, 1)), _FakeInstr("rz", (1,), (0.5,))]
    )
    circuit = from_qiskit(qc)
    assert [op.gate for op in circuit.ops] == ["H", "CNOT", "RZ"]
    assert circuit.ops[2].params == (0.5,)


def test_from_qiskit_rejects_unsupported_gates() -> None:
    with pytest.raises(ValueError, match="unsupported gate"):
        from_qiskit(_FakeQC(1, [_FakeInstr("ccx", (0, 1, 2))]))
