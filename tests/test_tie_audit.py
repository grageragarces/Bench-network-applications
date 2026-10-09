"""TieAudit: the verified, entanglement-steered audit of sign consistency."""

from __future__ import annotations

from functools import cache

import numpy as np
import pytest

from qnetbench.api import Basis, Gate
from qnetbench.apps import available_apps, catalog_apps
from qnetbench.apps.tie_audit import (
    TieAudit,
    apply_diagonal,
    apply_mct,
    confidence_interval,
    draw_twirl,
    linear_inverse_cnots,
    make_instance,
    pair_basis,
    synthesize_permutation,
)
from qnetbench.backends.reference.qstate import Register, gate_matrix
from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, line2
from qnetbench.trace.events import AppOutcomeEvent, ClassicalMessage, EntanglementRequested

# --- circuit building blocks ---------------------------------------------------------


class _RegQubit:
    """The portable Qubit protocol over a bare reference register."""

    def __init__(self, reg: Register, qid: int) -> None:
        self.reg, self.qid = reg, qid

    def apply(self, gate: Gate, *params: float) -> None:
        self.reg.apply_1q(self.qid, gate_matrix(gate.value, params))

    def cnot(self, target: _RegQubit) -> None:
        self.reg.cnot(self.qid, target.qid)

    def cz(self, target: _RegQubit) -> None:
        self.reg.cz(self.qid, target.qid)

    def measure(self, basis: Basis = Basis.Z) -> int:
        return self.reg.measure(self.qid, basis.value)

    def free(self) -> None:
        self.reg.free(self.qid)


class _Recorder:
    """A Qubit that only records the gate sequence applied to it."""

    def __init__(self, log: list[tuple[str, int, int]], index: int) -> None:
        self.log, self.index = log, index

    def apply(self, gate: Gate, *params: float) -> None:
        self.log.append((gate.value, self.index, -1))

    def cnot(self, target: _Recorder) -> None:
        self.log.append(("CNOT", self.index, target.index))

    def cz(self, target: _Recorder) -> None:
        self.log.append(("CZ", self.index, target.index))

    def measure(self, basis: Basis = Basis.Z) -> int:
        return 0

    def free(self) -> None:
        pass


def _register(n: int) -> tuple[Register, list[_RegQubit]]:
    reg = Register(np.random.default_rng(0))
    return reg, [_RegQubit(reg, reg.alloc()) for _ in range(n)]


def _amplitudes(reg: Register, n: int) -> np.ndarray:
    """Amplitude of |u>, with bit k of u on the k-th allocated qubit (the register
    itself is MSB-first)."""
    state = reg._state
    return np.array([state[int(format(u, f"0{n}b")[::-1], 2)] for u in range(1 << n)])


def _run_mct(gates: list[tuple[int, int]], x: int) -> int:
    for controls, target in gates:
        if x & controls == controls:
            x ^= 1 << target
    return x


@pytest.mark.parametrize("n", [2, 3, 4])
def test_apply_diagonal_reproduces_arbitrary_phases(n: int) -> None:
    reg, qubits = _register(n)
    for q in qubits:
        q.apply(Gate.H)
    phases = np.random.default_rng(n).uniform(0, 2 * np.pi, 1 << n)
    apply_diagonal(qubits, phases)
    ratio = _amplitudes(reg, n) / np.exp(1j * phases)
    assert np.allclose(ratio, ratio[0])  # equal up to one global phase
    assert np.isclose(abs(ratio[0]), 2 ** (-n / 2))


def test_fixed_diagonal_gate_sequence_does_not_depend_on_the_phases() -> None:
    """Alice's circuit must look the same on test and signal copies, or local gate
    noise would treat them differently and bias the estimate of η."""
    logs = []
    for phases in (np.zeros(8), np.random.default_rng(1).uniform(0, 2 * np.pi, 8)):
        log: list[tuple[str, int, int]] = []
        apply_diagonal([_Recorder(log, k) for k in range(3)], phases, fixed=True)
        logs.append(log)
    assert logs[0] == logs[1]
    assert sum(1 for g in logs[0] if g[0] == "CNOT") == 2**3 - 2


@pytest.mark.parametrize("n", [3, 4])
def test_apply_mct_is_a_multi_controlled_x(n: int) -> None:
    rng = np.random.default_rng(n)
    for _ in range(12):
        x0, target = int(rng.integers(0, 1 << n)), int(rng.integers(0, n))
        controls = int(rng.integers(0, 1 << n)) & ~(1 << target)
        reg, qubits = _register(n)
        for k, q in enumerate(qubits):
            if (x0 >> k) & 1:
                q.apply(Gate.X)
        apply_mct(qubits, controls, target)
        amps = _amplitudes(reg, n)
        assert np.isclose(abs(amps[_run_mct([(controls, target)], x0)]), 1.0)


@pytest.mark.parametrize("n", [2, 3, 4, 5])
def test_permutation_synthesis_realizes_the_permutation(n: int) -> None:
    rng = np.random.default_rng(n)
    for _ in range(50):
        perm = tuple(int(v) for v in rng.permutation(1 << n))
        gates = synthesize_permutation(perm, n)
        assert all(_run_mct(gates, x) == perm[x] for x in range(1 << n))


@pytest.mark.parametrize("n", [2, 3, 4, 5, 6])
def test_untwirl_circuit_inverts_the_affine_relabelling(n: int) -> None:
    rng = np.random.default_rng(n)
    for _ in range(30):
        tw = draw_twirl(rng, n, 0.5)
        ops = linear_inverse_cnots(tw.rows, n)
        for c in range(1 << n):
            x = tw.relabel(c) ^ tw.shift  # X^t first, then the CNOTs for A^-1
            for control, target in ops:
                if (x >> control) & 1:
                    x ^= 1 << target
            assert x == c


@pytest.mark.parametrize(("n", "alpha"), [(2, 1.0), (3, 1.0), (3, 0.5), (4, 0.75)])
def test_pair_basis_sends_each_pair_to_one_slot(n: int, alpha: float) -> None:
    inst = make_instance(n, alpha, 0.25, seed=7)
    basis = pair_basis(n, inst.pairs)
    bit = 1 << basis.pair_bit
    for k, (i, j) in enumerate(inst.pairs):
        yi, yj = _run_mct(list(basis.gates), i), _run_mct(list(basis.gates), j)
        assert yi ^ yj == bit
        assert basis.slot_of[yi & ~bit] == k


def test_make_instance_has_the_requested_conflict_fraction() -> None:
    inst = make_instance(4, 0.75, 0.5, seed=3)
    assert len(inst.pairs) == 6 and inst.matched_fraction == 0.75
    slots = [c for pair in inst.pairs for c in pair]
    assert len(set(slots)) == len(slots)  # a matching: disjoint pairs
    conflicts = sum(inst.signs[i] != inst.signs[j] for i, j in inst.pairs)
    assert inst.f == conflicts / len(inst.pairs) == 0.5


# --- the verified interval, independent of any simulator ----------------------------


def test_interval_is_sound_against_an_adaptive_source() -> None:
    """The source may pick each copy's attenuation from everything it has seen —
    here it starves the copies whenever the audit is going well — but it cannot see
    the labels, so the interval must still cover the true f at level 1 − δ."""
    rng = np.random.default_rng(11)
    trials, copies, alpha, q, delta, f = 300, 256, 0.75, 0.5, 0.05, 0.3
    covered = 0
    for _ in range(trials):
        signal_sum = test_sum = 0
        for _ in range(copies):
            eta = 0.1 if signal_sum + test_sum > 5 else 0.95
            test = rng.random() < q
            if rng.random() >= alpha:
                continue  # landed on an unmatched slot
            mean = eta * (1.0 if test else 1.0 - 2.0 * f)
            y = 1 if rng.random() < (1 + mean) / 2 else -1
            if test:
                test_sum += y
            else:
                signal_sum += y
        interval = confidence_interval(signal_sum, test_sum, copies, alpha, q, delta)
        covered += interval is not None and interval[0] <= f <= interval[1]
    assert covered / trials >= 1 - delta


def test_interval_without_signal_is_vacuous() -> None:
    lo, hi = confidence_interval(0, 0, 256, 1.0, 0.5, 0.05) or (None, None)
    assert (lo, hi) == (0.0, 1.0)


# --- the application ----------------------------------------------------------------


@cache
def _events(seed: int, fidelity: float = 1.0, copies: int = 256) -> tuple[object, ...]:
    topo = line2(link=LinkModel(link_fidelity=fidelity, fidelity_std=0.0))
    return tuple(run_once("tie_audit", seed=seed, topology=topo, cfg={"copies": copies}))


def _bob(events: tuple[object, ...]) -> dict[str, object]:
    return next(e.payload for e in events if isinstance(e, AppOutcomeEvent) and e.role == "bob")


def _eta_werner(fidelity: float, n: int = 3) -> float:
    """The exact twirled attenuation for i.i.d. Werner pairs: (P·F^n − (F+p_z)^n)/(P−1)."""
    size, pz = 2**n, (1 - fidelity) / 3
    return (size * fidelity**n - (fidelity + pz) ** n) / (size - 1)


def test_is_a_catalog_entry_not_a_core_protocol() -> None:
    assert "tie_audit" in catalog_apps()
    assert "tie_audit" not in available_apps()


@pytest.mark.parametrize("seed", range(4))
def test_noiseless_audit_is_verified(seed: int) -> None:
    events = _events(seed)
    report = compute_report(list(events))
    bob = _bob(events)
    assert bob["signal"] == 1.0  # every test copy returns +1: no attenuation
    assert bob["covered"] is True
    assert report.app_success
    assert report.app_utility > 0.6
    assert len({r.utility for r in report.roles}) == 1  # the verdict reaches Alice


def test_signal_matches_the_exact_twirl_identity() -> None:
    """E[Y | test] = α·η with η = (P·F_e − Λ)/(P−1); for Werner pairs at F = 0.9 and
    P = 8 that is 0.717, against 0.729 = F^3 for an untwirled estimate."""
    signals = [float(_bob(_events(seed, 0.9))["signal"]) for seed in range(12)]
    assert abs(np.mean(signals) - _eta_werner(0.9)) < 0.05


def test_utility_degrades_with_fidelity_but_the_interval_stays_sound() -> None:
    def runs(fidelity: float) -> list[dict[str, object]]:
        return [_bob(_events(seed, fidelity)) for seed in range(6)]

    def mean_utility(fidelity: float) -> float:
        reports = [compute_report(list(_events(s, fidelity))) for s in range(6)]
        return float(np.mean([r.app_utility for r in reports]))

    assert mean_utility(1.0) >= mean_utility(0.9) >= mean_utility(0.7)
    assert mean_utility(0.7) < mean_utility(1.0) - 0.1
    assert all(p["covered"] for p in runs(0.7))  # wider, never wrong


def test_each_copy_is_n_pairs_and_n_one_way_bits() -> None:
    events = run_once("tie_audit", seed=0, cfg={"copies": 8})
    requests = [e for e in events if isinstance(e, EntanglementRequested)]
    assert len(requests) == 8 and all(e.n == 3 for e in requests)
    msgs = [e for e in events if isinstance(e, ClassicalMessage)]
    forward = [e for e in msgs if e.src == "alice"]
    backward = [e for e in msgs if e.src == "bob"]
    assert len(forward) == 1 + 8  # the setup seed, then one message per copy
    assert all(e.n_bytes == 1 for e in forward[1:])  # n = 3 bits
    assert len(backward) == 1  # only the closing verdict travels back


def test_rejects_an_out_of_range_size() -> None:
    with pytest.raises(ValueError, match="2 <= n"):
        TieAudit().run(None, "alice", {"n": 9})  # type: ignore[arg-type]
