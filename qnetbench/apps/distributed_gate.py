"""A non-local (teleported) CNOT between a control qubit on Alice and a target
qubit on Bob, via one shared EPR pair and two classical bits — the Gottesman–Chuang
cat-entangler/disentangler construction.

Demand signature: deadline-critical and staleness-intolerant. The gate blocks the
distributed circuit, so the pair carries a hard `deadline` and a tight
`staleness_tolerance`. Utility is the fraction of repetitions reproducing the CNOT
truth table |c,t> → |c, t⊕c>.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Basis, Demand, Gate, Host, Role
from qnetbench.apps.telegate import telegate_control, telegate_target
from qnetbench.apps.util import cfg_int


class DistributedGate:
    name = "distributed_gate"

    def __init__(
        self,
        reps: int = 8,
        min_fidelity: float = 0.9,
        deadline_budget: float = 0.05,
    ) -> None:
        self.reps = reps
        self.min_fidelity = min_fidelity
        self.deadline_budget = deadline_budget

    def roles(self) -> list[Role]:
        return ["alice", "bob"]  # alice = control, bob = target

    def _demand(self, host: Host) -> Demand:
        return Demand(
            min_fidelity=self.min_fidelity,
            deadline=host.now() + self.deadline_budget,
            staleness_tolerance=1e-3,
            purpose="keep",
        )

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        reps = cfg_int(cfg, "reps", self.reps)
        if role == "alice":
            return self._control(host, reps)
        return self._target(host, reps)

    def _control(self, host: Host, reps: int) -> AppOutcome:
        epr = host.epr_socket("bob")
        cls = host.classical_socket("bob")
        c_inputs: list[int] = []
        c_outputs: list[int] = []
        for rep in range(reps):
            c = rep % 2  # sweep control input
            c_inputs.append(c)
            data = host.qalloc()
            if c:
                data.apply(Gate.X)
            telegate_control(data, epr, cls, self._demand(host))  # non-local CNOT
            c_outputs.append(data.measure(Basis.Z))

        # Reconciliation for scoring (not part of the protocol).
        cls.send(bytes(c_inputs))
        reconciled = cls.recv()
        t_inputs = list(reconciled[:reps])
        t_outputs = list(reconciled[reps:])
        correct = sum(
            1 for i in range(reps) if t_outputs[i] == (t_inputs[i] ^ c_inputs[i])
        )
        utility = correct / reps if reps else 0.0
        return AppOutcome(
            role="alice",
            success=correct == reps,
            utility=utility,
            payload={"reps": reps, "correct": correct},
        )

    def _target(self, host: Host, reps: int) -> AppOutcome:
        epr = host.epr_socket("alice")
        cls = host.classical_socket("alice")
        t_inputs: list[int] = []
        t_outputs: list[int] = []
        for rep in range(reps):
            t = (rep // 2) % 2  # sweep target input
            t_inputs.append(t)
            data = host.qalloc()
            if t:
                data.apply(Gate.X)
            telegate_target(data, epr, cls, self._demand(host))  # non-local CNOT
            t_outputs.append(data.measure(Basis.Z))

        c_inputs = list(cls.recv())
        cls.send(bytes(t_inputs) + bytes(t_outputs))
        correct = sum(
            1 for i in range(reps) if t_outputs[i] == (t_inputs[i] ^ c_inputs[i])
        )
        utility = correct / reps if reps else 0.0
        return AppOutcome(
            role="bob",
            success=correct == reps,
            utility=utility,
            payload={"reps": reps, "correct": correct},
        )
