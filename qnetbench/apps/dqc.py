"""Distributed quantum computing (DQC): execute a partitioned circuit across nodes.

The demand comes from a real circuit, not a hand-set contract. Each node runs its
slice: single-qubit and same-node two-qubit gates apply locally; every *non-local*
two-qubit gate becomes a teleported gate — one entanglement request whose deadline
is the gate's ASAP layer × a per-layer budget. So the trace's entanglement requests
are the circuit's Entanglement Demand Schedule.

Demand signature: bursty and deadline-critical, with a shape set by the circuit
(gate count, non-local fraction, depth). Library circuits are mirror circuits
(U;U†), so a noiseless run returns every qubit to |0>; utility is the fraction of
qubits measured 0, which degrades as teleported-gate fidelity drops.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Basis, Demand, Gate, Host, Qubit, Role
from qnetbench.apps.telegate import telegate_control, telegate_target
from qnetbench.circuits import Circuit, Op

_NODE = {"alice": 0, "bob": 1}
_PEER = {"alice": "bob", "bob": "alice"}


class DQC:
    """A DQC benchmark for one (2-node) partitioned circuit."""

    def __init__(
        self, circuit: Circuit, min_fidelity: float = 0.9, layer_budget: float = 1e-2
    ) -> None:
        if set(circuit.partition) - {0, 1}:
            raise ValueError("DQC currently supports 2-node (alice/bob) partitions only")
        self.circuit = circuit
        self.name = f"dqc_{circuit.name}"
        self.min_fidelity = min_fidelity
        self.layer_budget = layer_budget

    def roles(self) -> list[Role]:
        return ["alice", "bob"]

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        node = _NODE[role]
        circuit = self.circuit
        epr = host.epr_socket(_PEER[role])
        cls = host.classical_socket(_PEER[role])

        qubits: dict[int, Qubit] = {
            q: host.qalloc() for q in range(circuit.n_qubits) if circuit.partition[q] == node
        }
        for op, layer in zip(circuit.ops, circuit.layers(), strict=True):
            self._apply(op, layer, node, qubits, epr, cls)

        # Mirror circuit: every qubit should read 0 noiselessly.
        zeros = sum(1 for q in qubits.values() if q.measure(Basis.Z) == 0)
        total = len(qubits)

        # Reconcile the two halves for a global success measure.
        cls.send(bytes([zeros, total]))
        their_zeros, their_total = cls.recv()[:2]
        all_zeros, all_total = zeros + their_zeros, total + their_total
        return AppOutcome(
            role=role,
            success=all_zeros == all_total,
            utility=all_zeros / all_total if all_total else 0.0,
            payload={"n_nonlocal": circuit.n_nonlocal(), "depth": circuit.depth()},
        )

    def _apply(
        self,
        op: Op,
        layer: int,
        node: int,
        qubits: dict[int, Qubit],
        epr: object,
        cls: object,
    ) -> None:
        circuit = self.circuit
        if len(op.qubits) == 1:  # single-qubit gate: the owner applies it
            q = op.qubits[0]
            if circuit.partition[q] == node:
                qubits[q].apply(Gate[op.gate], *op.params)
            return

        a, b = op.qubits
        if circuit.partition[a] == node and circuit.partition[b] == node:  # local two-qubit gate
            if op.gate == "CNOT":
                qubits[a].cnot(qubits[b])
            else:  # CZ
                qubits[a].cz(qubits[b])
        elif circuit.is_nonlocal(op):  # teleported gate — the entanglement demand
            self._telegate(op, node, qubits, epr, cls, self._demand(layer))
        # else: a local gate wholly on the other node — nothing for us to do.

    def _telegate(
        self,
        op: Op,
        node: int,
        qubits: dict[int, Qubit],
        epr: object,
        cls: object,
        demand: Demand,
    ) -> None:
        a, b = op.qubits  # a = control, b = target
        i_hold_control = self.circuit.partition[a] == node
        # CZ = H_target · CNOT · H_target, so the target side brackets a CNOT with H.
        if op.gate == "CZ" and not i_hold_control:
            qubits[b].apply(Gate.H)
        if i_hold_control:
            telegate_control(qubits[a], epr, cls, demand)  # type: ignore[arg-type]
        else:
            telegate_target(qubits[b], epr, cls, demand)  # type: ignore[arg-type]
        if op.gate == "CZ" and not i_hold_control:
            qubits[b].apply(Gate.H)

    def _demand(self, layer: int) -> Demand:
        return Demand(
            min_fidelity=self.min_fidelity,
            deadline=layer * self.layer_budget,  # circuit-derived: deeper gates are due later
            staleness_tolerance=1e-3,
            purpose="keep",
        )
