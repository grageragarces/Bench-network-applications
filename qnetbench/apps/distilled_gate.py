"""A distilled distributed gate: best-effort entanglement refined into a
deadline-critical one.

This is how a buffer-backed repeater node actually operates, and it is the only
application in the suite that issues *two demand classes at once*. Bulk raw pairs
are requested best-effort — no deadline, a low fidelity bar — and distilled into one
good pair; that pair then carries a teleported CNOT, which is deadline-critical
because it blocks the distributed circuit. When a distillation step is heralded as
failed, the gate still has to happen, so the node falls back to a fresh pair drawn
under the tight gate contract.

Demand signature: **mixed criticality**. Every other application in the suite is
either wholly deadline-bearing (`deadline` = 1.00) or wholly best-effort
(`deadline` = 0.00); this one sits strictly between, and the ratio is set by the
distillation failure rate, so it moves with link quality. That is the case a
scheduler exists to arbitrate, and it previously arose only *between* tenants,
never inside one workload.

Utility is the fraction of repetitions reproducing the CNOT truth table
|c,t> → |c, t⊕c>.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Basis, Demand, Gate, Host, Qubit, Role
from qnetbench.apps.purify import distill_step
from qnetbench.apps.telegate import telegate_control_with, telegate_target_with
from qnetbench.apps.util import cfg_int

_SIGN = {"alice": 1, "bob": -1}


class DistilledGate:
    name = "distilled_gate"

    def __init__(
        self,
        reps: int = 12,
        bulk_min_fidelity: float = 0.5,
        gate_min_fidelity: float = 0.9,
        deadline_budget: float = 0.05,
    ) -> None:
        self.reps = reps
        self.bulk_min_fidelity = bulk_min_fidelity
        self.gate_min_fidelity = gate_min_fidelity
        self.deadline_budget = deadline_budget

    def roles(self) -> list[Role]:
        return ["alice", "bob"]  # alice = control, bob = target

    def _bulk_demand(self) -> Demand:
        """Background entanglement: cheap, plentiful, no deadline."""
        return Demand(min_fidelity=self.bulk_min_fidelity, purpose="keep")

    def _gate_demand(self, host: Host) -> Demand:
        """Foreground entanglement: the gate blocks the circuit."""
        return Demand(
            min_fidelity=self.gate_min_fidelity,
            deadline=host.now() + self.deadline_budget,
            staleness_tolerance=1e-3,
            purpose="keep",
        )

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        reps = cfg_int(cfg, "reps", self.reps)
        peer = "bob" if role == "alice" else "alice"
        epr = host.epr_socket(peer)
        cls = host.classical_socket(peer)

        inputs: list[int] = []
        outputs: list[int] = []
        distilled = 0
        for rep in range(reps):
            # --- best-effort: two bulk pairs, distilled into one ---------------
            handles = epr.request(2, self._bulk_demand())
            keep, sacrifice = handles[0].qubit, handles[1].qubit
            assert keep is not None and sacrifice is not None
            if distill_step(keep, sacrifice, cls, sign=_SIGN[role]):
                gate_pair: Qubit = keep
                distilled += 1
            else:
                keep.free()
                # Fall back to a fresh pair under the deadline-bearing contract:
                # the gate is due whether or not distillation happened to work.
                fresh = epr.request(1, self._gate_demand(host))[0].qubit
                assert fresh is not None
                gate_pair = fresh

            # --- deadline-critical: the non-local CNOT over that pair ----------
            bit = rep % 2 if role == "alice" else (rep // 2) % 2
            inputs.append(bit)
            data = host.qalloc()
            if bit:
                data.apply(Gate.X)
            if role == "alice":
                telegate_control_with(data, gate_pair, cls)
            else:
                telegate_target_with(data, gate_pair, cls)
            outputs.append(data.measure(Basis.Z))

        # Reconciliation for scoring (not part of the protocol).
        if role == "alice":
            cls.send(bytes(inputs))
            reconciled = cls.recv()
            t_inputs, t_outputs = list(reconciled[:reps]), list(reconciled[reps:])
            c_inputs = inputs
        else:
            c_inputs = list(cls.recv())
            cls.send(bytes(inputs) + bytes(outputs))
            t_inputs, t_outputs = inputs, outputs

        correct = sum(1 for i in range(reps) if t_outputs[i] == (t_inputs[i] ^ c_inputs[i]))
        return AppOutcome(
            role=role,
            success=correct == reps,
            utility=correct / reps if reps else 0.0,
            payload={
                "reps": reps,
                "correct": correct,
                "distilled": distilled,
                "fallback_pairs": reps - distilled,
            },
        )
