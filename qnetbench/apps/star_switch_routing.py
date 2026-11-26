"""Multi-qubit-per-node star-switch multipartite routing benchmark.

Four end-nodes (`leaf0`..`leaf3`) connected to a central `hub` each receive a
two-qubit share of an eight-qubit CSS multipartite resource state (the binary lift
of the [4, 2, 3]_4 MDS code over F_4, teleported two qubits at a time from the hub
across the star links). After distribution, a dynamic perfect matching
M in { {(0,1),(2,3)}, {(0,2),(1,3)}, {(0,3),(1,2)} } is revealed: each leaf measures
one of its two qubits in a prescribed local Pauli basis (X or Z) to carve out two
*simultaneous* point-to-point Bell pairs covering all four leaves, without additional
quantum communication.

Each round checks both extracted Bell pairs in a randomly chosen Pauli basis
(Z⊗Z or X⊗X), accounting for the exact classical Pauli-frame parity from the four
local routing measurements. Utility is the fraction of rounds in which *both*
simultaneously extracted pairs exhibit the expected Bell correlation (1.0 noiselessly,
degrading smoothly with elementary-link fidelity and memory decay).

Demand signature: multi-qubit burst requests (2 EPR pairs per leaf, 8 pairs per
round across a 5-node star), hub-side CSS state preparation with teleported
distribution, and dynamic multi-pair extraction via single-node local measurements.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Basis, ClassicalSocket, Demand, EPRSocket, Gate, Host, Role
from qnetbench.apps.util import cfg_int

_LEAVES: tuple[str, ...] = ("leaf0", "leaf1", "leaf2", "leaf3")

# 8-qubit CSS encoder preparing (1/4) sum_{x,y in F_4} |x, y, x+y, x+w*y> from |0>^8,
# with leaf p holding qubits (2p, 2p+1) and w*(y0, y1) = (y1, y0 ^ y1).
_HADAMARDS: tuple[int, ...] = (0, 1, 2, 3)
_CNOTS: tuple[tuple[int, int], ...] = (
    (0, 4), (2, 4),
    (1, 5), (3, 5),
    (0, 6), (3, 6),
    (1, 7), (2, 7), (3, 7),
)

# For each of the 3 dynamic perfect matchings on {0, 1, 2, 3}:
#   (pairs, leaf_meas_cfg, (z1_mask, x1_mask, z2_mask, x2_mask))
# where leaf_meas_cfg[p] = (qubit_idx_to_measure in {0, 1}, basis_char in {"X", "Z"})
# and each 4-bit mask gives the exact Pauli-frame parity bit as popcount(mask & m_bits) % 2
# over the 4 local routing outcomes m_bits = sum_p (m_p << p).
_MATCHING_SCHEDULES: tuple[
    tuple[
        tuple[tuple[int, int], tuple[int, int]],
        tuple[tuple[int, str], ...],
        tuple[int, int, int, int],
    ],
    ...,
] = (
    (((0, 1), (2, 3)), ((0, "Z"), (0, "X"), (1, "Z"), (0, "X")), (4, 8, 5, 2)),
    (((0, 2), (1, 3)), ((0, "X"), (1, "Z"), (0, "Z"), (1, "X")), (2, 8, 6, 9)),
    (((0, 3), (1, 2)), ((0, "X"), (1, "X"), (0, "Z"), (1, "Z")), (12, 2, 8, 3)),
)


def _parity(x: int) -> int:
    return bin(x).count("1") & 1


class StarSwitchRouting:
    """5-node star-switch multipartite routing benchmark (1 hub + 4 two-qubit leaves)."""

    name = "star_switch_routing"

    def __init__(self, rounds: int = 32, min_fidelity: float = 0.9) -> None:
        self.rounds = rounds
        self.min_fidelity = min_fidelity

    def roles(self) -> list[Role]:
        return ["hub", *_LEAVES]

    def _demand(self) -> Demand:
        return Demand(min_fidelity=self.min_fidelity, purpose="keep")

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        rounds = cfg_int(cfg, "rounds", self.rounds)
        if role == "hub":
            return self._hub(host, rounds)
        return self._leaf(host, role, rounds)

    def _hub(self, host: Host, rounds: int) -> AppOutcome:
        eprs: list[EPRSocket] = [host.epr_socket(leaf) for leaf in _LEAVES]
        clss: list[ClassicalSocket] = [host.classical_socket(leaf) for leaf in _LEAVES]
        passed = 0

        for _ in range(rounds):
            # 1. Prepare the 8-qubit CSS state locally at the hub.
            state_q = [host.qalloc() for _ in range(8)]
            for q_idx in _HADAMARDS:
                state_q[q_idx].apply(Gate.H)
            for ctrl, tgt in _CNOTS:
                state_q[ctrl].cnot(state_q[tgt])

            # 2. Teleport 2 qubits to each leaf (sequentially per leaf to keep live
            #    qubit count <= 10 on statevector backends).
            for leaf_idx, (epr, cls) in enumerate(zip(eprs, clss, strict=True)):
                pairs = epr.request(2, self._demand())
                corr_bits: list[int] = []
                for k in range(2):
                    src = state_q[2 * leaf_idx + k]
                    epr_half = pairs[k].qubit
                    assert epr_half is not None
                    src.cnot(epr_half)
                    src.apply(Gate.H)
                    m_z = src.measure(Basis.Z)
                    m_x = epr_half.measure(Basis.Z)
                    corr_bits.extend((m_z, m_x))
                cls.send(bytes(corr_bits))

            # 3. Reveal dynamic matching M and verification basis (0=Z, 1=X).
            m_idx = int(host.rng.integers(0, len(_MATCHING_SCHEDULES)))
            check_x = int(host.rng.integers(0, 2))
            for cls in clss:
                cls.send(bytes([m_idx, check_x]))

            # 4. Collect (routing_outcome, verification_outcome) from all 4 leaves.
            m_bits = 0
            v_bits = [0, 0, 0, 0]
            for leaf_idx, cls in enumerate(clss):
                r_bit, v_bit = cls.recv()[:2]
                m_bits |= (r_bit & 1) << leaf_idx
                v_bits[leaf_idx] = v_bit & 1

            # 5. Check exact Bell-pair correlation on BOTH simultaneously extracted pairs.
            (pair1, pair2), _, (z1_m, x1_m, z2_m, x2_m) = _MATCHING_SCHEDULES[m_idx]
            exp1 = _parity((x1_m if check_x else z1_m) & m_bits)
            exp2 = _parity((x2_m if check_x else z2_m) & m_bits)
            ok1 = (v_bits[pair1[0]] ^ v_bits[pair1[1]]) == exp1
            ok2 = (v_bits[pair2[0]] ^ v_bits[pair2[1]]) == exp2
            if ok1 and ok2:
                passed += 1

        for cls in clss:
            cls.send(bytes([passed >> 8, passed & 0xFF]))
        return _outcome("hub", passed, rounds)

    def _leaf(self, host: Host, role: Role, rounds: int) -> AppOutcome:
        leaf_idx = int(role.replace("leaf", ""))
        epr = host.epr_socket("hub")
        cls = host.classical_socket("hub")

        for _ in range(rounds):
            pairs = epr.request(2, self._demand())
            q0, q1 = pairs[0].qubit, pairs[1].qubit
            assert q0 is not None and q1 is not None
            qubits = (q0, q1)

            # Apply teleportation Pauli corrections from hub.
            c0_z, c0_x, c1_z, c1_x = cls.recv()[:4]
            if c0_x:
                qubits[0].apply(Gate.X)
            if c0_z:
                qubits[0].apply(Gate.Z)
            if c1_x:
                qubits[1].apply(Gate.X)
            if c1_z:
                qubits[1].apply(Gate.Z)

            # Receive dynamic matching and verification basis.
            m_idx, check_x = cls.recv()[:2]
            _, leaf_cfgs, _ = _MATCHING_SCHEDULES[m_idx]
            meas_q, meas_basis_str = leaf_cfgs[leaf_idx]
            keep_q = 1 - meas_q

            # Measure routing qubit in local X or Z basis; measure surviving Bell half.
            r_bit = qubits[meas_q].measure(Basis.X if meas_basis_str == "X" else Basis.Z)
            v_bit = qubits[keep_q].measure(Basis.X if check_x else Basis.Z)
            cls.send(bytes([r_bit, v_bit]))

        tally = cls.recv()
        return _outcome(role, (tally[0] << 8) | tally[1], rounds)


def _outcome(role: Role, passed: int, rounds: int) -> AppOutcome:
    return AppOutcome(
        role=role,
        success=passed == rounds,
        utility=passed / rounds if rounds else 0.0,
        payload={"rounds": rounds, "passed": passed},
    )
