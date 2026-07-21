"""Unit tests for the reference statevector simulator — the physics the whole
suite's correctness rests on."""

from __future__ import annotations

import numpy as np

from qnetbench.backends.reference.qstate import Register, gate_matrix


def _reg(seed: int = 0) -> Register:
    return Register(np.random.default_rng(seed))


def test_x_flips_and_measurement_is_destructive() -> None:
    reg = _reg()
    q = reg.alloc()
    reg.apply_1q(q, gate_matrix("X", ()))
    assert reg.n == 1
    assert reg.measure(q, "Z") == 1
    assert reg.n == 0  # measurement frees the qubit


def test_bell_pair_is_perfectly_correlated_in_z_and_x() -> None:
    for basis in ("Z", "X"):
        agree = 0
        for s in range(200):
            reg = _reg(s)
            a, b = reg.make_bell_pair(1.0)
            if reg.measure(a, basis) == reg.measure(b, basis):
                agree += 1
        assert agree == 200, basis


def test_werner_noise_lowers_correlation() -> None:
    fidelity = 0.8
    disagree = 0
    trials = 2000
    for s in range(trials):
        reg = _reg(s)
        a, b = reg.make_bell_pair(fidelity)
        if reg.measure(a, "Z") != reg.measure(b, "Z"):
            disagree += 1
    # Werner state: P(error | matched basis) = 2(1-F)/3.
    expected = 2 * (1 - fidelity) / 3
    assert abs(disagree / trials - expected) < 0.03


def test_chsh_reaches_tsirelson_bound() -> None:
    def measure_obs(reg: Register, qid: int, angle: float) -> int:
        reg.apply_1q(qid, gate_matrix("RY", (-angle,)))
        return 1 - 2 * reg.measure(qid, "Z")  # +1 / -1

    settings = {
        ("a0", "b0"): (0.0, np.pi / 4),
        ("a0", "b1"): (0.0, -np.pi / 4),
        ("a1", "b0"): (np.pi / 2, np.pi / 4),
        ("a1", "b1"): (np.pi / 2, -np.pi / 4),
    }
    corr = {}
    trials = 4000
    for offset, (key, (pa, pb)) in enumerate(settings.items()):
        total = 0
        for s in range(trials):
            reg = _reg(offset * 100_000 + s)  # deterministic, disjoint seed ranges
            a, b = reg.make_bell_pair(1.0)
            total += measure_obs(reg, a, pa) * measure_obs(reg, b, pb)
        corr[key] = total / trials
    s_value = corr[("a0", "b0")] + corr[("a0", "b1")] + corr[("a1", "b0")] - corr[("a1", "b1")]
    assert abs(s_value) > 2.6  # violates the classical bound of 2, near 2√2 ≈ 2.83
