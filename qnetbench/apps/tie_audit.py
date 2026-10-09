"""TieAudit: a verified, entanglement-steered audit of sign consistency.

Alice holds signs s over P = 2^n slots (in a ring all-reduce, the tie-breaking
sign each slot was given); Bob holds a matching M of the slots and wants f, the
fraction of matched pairs whose signs disagree (the task of arXiv:2606.20344).
One *copy* of the protocol consumes n Bell pairs and n classical bits, sent from
Alice to Bob only:

1. Alice applies the phase diag(s) to her n halves and measures each in X.
2. Bob measures his n halves in M's pair basis (|i> ± |j>)/√2. Together with
   Alice's bits this reveals s_i·s_j for one uniformly random matched pair.

Each copy is twirled by a fresh random affine relabelling of the slots and a
random diagonal-Clifford phase pad, drawn from randomness Alice and Bob share in
advance. The twirl turns *any* noise on the pairs into a single attenuation η, so
E[Y] = α·η·(1 − 2f) exactly, where α is the fraction of slots M covers. A hidden
random subset of copies are *tests*, on which Alice encodes the all-agree string
(f = 0). The source cannot tell them apart, so they measure η on the very pairs it
delivered: with A and B the signal and test sums and q the test fraction,
D(f) = q·A − (1 − q)(1 − 2f)·B is a martingale for the true f under any source,
and Freedman's inequality turns it into a confidence interval for f at level
1 − δ — no calibration run, no i.i.d. assumption.

Demand signature: n pairs consumed jointly per copy (the signal decays like F^n),
strictly one-way classical traffic while pairs are in use, no feed-forward (both
halves are measured on arrival, so classical latency never ages a qubit), and the
overhead of hidden test copies — the price of verification.

Utility is the share of [0, 1] the verified interval rules out, 1 − (hi − lo), or
0 when the interval misses the true f (ground truth, used for scoring only).
Success means the interval holds f with half-width at most `eps`. At the end Bob
announces his verdict, so both roles report the same outcome.

The default instance is a toy (P = 8), where Alice could simply send s; the
communication advantage is asymptotic in P. What transfers is what the workload
measures: the demand of n-pair bursts, the fidelity response η(F), and the cost
of verifying an untrusted source.
"""

from __future__ import annotations

import itertools
import math
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from numpy.typing import NDArray

from qnetbench.api import AppOutcome, Basis, Demand, Gate, Host, Qubit, Role
from qnetbench.apps.util import cfg_float, cfg_int

# Above 2^(-1/4) ≈ 0.841 per pair, the twirled signal η ≈ F^n shrinks more slowly
# than the best classical protocol's cost (~√P bits) grows, so the quantum audit
# keeps an asymptotic advantage; below it the advantage is gone at any scale.
_ADVANTAGE_FIDELITY = 0.84
_MAX_N = 6  # the reference backend's statevector costs ~4^n per copy
_VERDICT = struct.Struct("<ddd?")  # lo, hi, utility, success


# --- instance -------------------------------------------------------------------


@dataclass(frozen=True)
class Instance:
    """One TieAudit input: Alice's signs and Bob's matching. `f` is ground truth."""

    n: int
    signs: tuple[int, ...]  # s_c in {+1, -1} for slot c in [0, 2^n)
    pairs: tuple[tuple[int, int], ...]  # Bob's matching M
    f: float  # fraction of matched pairs whose signs disagree

    @property
    def matched_fraction(self) -> float:
        return 2 * len(self.pairs) / (1 << self.n)


def make_instance(n: int, matched_fraction: float, conflict_fraction: float, seed: int) -> Instance:
    """A random matching over round(matched_fraction · 2^(n-1)) pairs, with exactly
    round(conflict_fraction · pairs) of them carrying disagreeing signs."""
    size = 1 << n
    rng = np.random.default_rng(seed)
    order = rng.permutation(size)
    n_pairs = min(size // 2, max(1, round(matched_fraction * size / 2)))
    pairs = tuple((int(order[2 * k]), int(order[2 * k + 1])) for k in range(n_pairs))
    signs = [int(x) for x in rng.choice((-1, 1), size=size)]
    n_conflict = min(n_pairs, max(0, round(conflict_fraction * n_pairs)))
    conflicted = {int(k) for k in rng.choice(n_pairs, size=n_conflict, replace=False)}
    for k, (i, j) in enumerate(pairs):
        signs[j] = -signs[i] if k in conflicted else signs[i]
    return Instance(n=n, signs=tuple(signs), pairs=pairs, f=n_conflict / n_pairs)


# --- per-copy shared secret -------------------------------------------------------


def _parity(x: int) -> int:
    return bin(x).count("1") & 1


def _rank(rows: tuple[int, ...], n: int) -> int:
    m, rank = list(rows), 0
    for col in range(n):
        pivot = next((r for r in range(rank, n) if (m[r] >> col) & 1), None)
        if pivot is None:
            continue
        m[rank], m[pivot] = m[pivot], m[rank]
        for r in range(n):
            if r != rank and (m[r] >> col) & 1:
                m[r] ^= m[rank]
        rank += 1
    return rank


@dataclass(frozen=True)
class Twirl:
    """One copy's shared secret: its test/signal label, an affine relabelling
    π(c) = A·c ⊕ t of the slots, and a diagonal-Clifford pad r_u = i^pad(u)."""

    test: bool
    rows: tuple[int, ...]  # row k of A as a bitmask: (A·c)_k = parity(rows[k] & c)
    shift: int  # t
    lin: tuple[int, ...]  # pad(u) = Σ_k lin[k]·u_k ...
    quad: tuple[tuple[int, int], ...]  # ... + 2·Σ_(k,l) u_k·u_l   (mod 4)

    def relabel(self, c: int) -> int:
        y = 0
        for k, row in enumerate(self.rows):
            y |= _parity(row & c) << k
        return y ^ self.shift

    def pad(self, u: int) -> int:
        p = sum(a for k, a in enumerate(self.lin) if (u >> k) & 1)
        p += 2 * sum(1 for k, j in self.quad if (u >> k) & 1 and (u >> j) & 1)
        return p % 4


def draw_twirl(rng: np.random.Generator, n: int, test_fraction: float) -> Twirl:
    """Both roles call this in lockstep on generators seeded alike, so they agree."""
    test = bool(rng.random() < test_fraction)
    while True:
        rows = tuple(int(rng.integers(0, 1 << n)) for _ in range(n))
        if _rank(rows, n) == n:
            break
    shift = int(rng.integers(0, 1 << n))
    lin = tuple(int(rng.integers(0, 4)) for _ in range(n))
    quad = tuple(pair for pair in itertools.combinations(range(n), 2) if rng.random() < 0.5)
    return Twirl(test=test, rows=rows, shift=shift, lin=lin, quad=quad)


# --- circuits over the portable gate set -----------------------------------------


def _walsh(values: NDArray[np.float64]) -> NDArray[np.float64]:
    out = values.astype(float).copy()
    h = 1
    while h < len(out):
        for start in range(0, len(out), 2 * h):
            a = out[start : start + h].copy()
            b = out[start + h : start + 2 * h].copy()
            out[start : start + h] = a + b
            out[start + h : start + 2 * h] = a - b
        h *= 2
    return out


def apply_diagonal(
    qubits: list[Qubit], phases: NDArray[np.float64], *, fixed: bool = False
) -> None:
    """Apply diag(exp(i·phases[u])) to `qubits` (bit k of u is qubits[k]), up to a
    global phase, with 2^n − 2 CNOTs.

    Walsh decomposition, phases[u] = Σ_w θ_w (−1)^(w·u), so the diagonal is a product
    of RZ(−2θ_w) rotations on the parities w·u. The parities whose highest bit is
    `top` are visited in Gray-code order on qubit `top`, one CNOT per step.
    `fixed=True` keeps every rotation even when its angle vanishes, so the gate
    sequence does not depend on the phases (test copies must look like signal ones).
    """
    theta = _walsh(phases) / len(phases)
    angles = [math.remainder(float(t), math.pi) for t in theta]  # θ ~ θ+π: a global phase
    for top in range(len(qubits) - 1, -1, -1):
        block = [(1 << top) | (s ^ (s >> 1)) for s in range(1 << top)]
        if not fixed and all(abs(angles[w]) < 1e-12 for w in block):
            continue
        target = qubits[top]
        for step, w in enumerate(block):
            if step:  # Gray-code neighbours differ in one lower qubit: fold it in or out
                qubits[(w ^ block[step - 1]).bit_length() - 1].cnot(target)
            if fixed or abs(angles[w]) >= 1e-12:
                target.apply(Gate.RZ, -2.0 * angles[w])
        if top:  # the last Gray code is the single bit top−1: restore the target
            qubits[top - 1].cnot(target)


def apply_mct(qubits: list[Qubit], controls: int, target: int) -> None:
    """X on qubits[target] when every qubit in the `controls` bitmask is 1."""
    ctrl = [k for k in range(len(qubits)) if (controls >> k) & 1]
    if not ctrl:
        qubits[target].apply(Gate.X)
    elif len(ctrl) == 1:
        qubits[ctrl[0]].cnot(qubits[target])
    else:  # H · (multi-controlled Z) · H, the controlled-Z as a diagonal
        involved = [qubits[k] for k in ctrl] + [qubits[target]]
        phases = np.zeros(1 << len(involved))
        phases[-1] = math.pi
        qubits[target].apply(Gate.H)
        apply_diagonal(involved, phases)
        qubits[target].apply(Gate.H)


def synthesize_permutation(perm: tuple[int, ...], n: int) -> list[tuple[int, int]]:
    """A multi-controlled-X cascade realizing |x> -> |perm[x]>, as (control mask,
    target) in circuit order: transformation-based synthesis (Miller, Maslov and
    Dueck, DAC 2003). Each gate is fixed at the output side; values already placed
    are never disturbed, because their bits cannot cover the gate's controls."""
    f = list(perm)
    gates: list[tuple[int, int]] = []

    def push(controls: int, target: int) -> None:
        gates.append((controls, target))
        for idx, val in enumerate(f):
            if val & controls == controls:
                f[idx] = val ^ (1 << target)

    for x in range(len(f)):
        for k in range(n):  # raise the bits x has and f(x) lacks, controlled on f(x)
            if (x >> k) & 1 and not (f[x] >> k) & 1:
                push(f[x], k)
        for k in range(n):  # lower the bits f(x) has and x lacks, controlled on x
            if (f[x] >> k) & 1 and not (x >> k) & 1:
                push(x, k)
    return gates[::-1]


def _cnot_cost(gates: list[tuple[int, int]]) -> int:
    """CNOTs `apply_mct` spends: 0, 1, then 2^(c+1) − 2 for c >= 2 controls."""
    total = 0
    for controls, _ in gates:
        c = bin(controls).count("1")
        total += c if c < 2 else (1 << (c + 1)) - 2
    return total


def linear_inverse_cnots(rows: tuple[int, ...], n: int) -> list[tuple[int, int]]:
    """CNOTs (control, target) realizing |c> -> |A⁻¹·c>: Gauss–Jordan elimination
    of A, each row operation row_t ⊕= row_c being a CNOT from qubit c onto qubit t."""
    m = list(rows)
    ops: list[tuple[int, int]] = []
    for col in range(n):
        if not (m[col] >> col) & 1:
            r = next(r for r in range(col + 1, n) if (m[r] >> col) & 1)
            m[col] ^= m[r]
            ops.append((r, col))
        for r in range(n):
            if r != col and (m[r] >> col) & 1:
                m[r] ^= m[col]
                ops.append((col, r))
    return ops


@dataclass(frozen=True)
class PairBasis:
    """Bob's fixed measurement of M's pair basis: a permutation sending each matched
    pair to two strings that differ only in bit `pair_bit`, then H on that bit."""

    gates: tuple[tuple[int, int], ...]  # MCT cascade, circuit order
    pair_bit: int
    slot_of: dict[int, int]  # base string (pair bit cleared) -> index into M


@lru_cache(maxsize=32)
def pair_basis(n: int, pairs: tuple[tuple[int, int], ...]) -> PairBasis:
    """The cheapest such permutation found (by CNOT count), over the choice of pair
    bit, slot per pair, orientation and placement of the unmatched slots —
    exhaustively when that is small, else over a fixed random sample."""
    size = 1 << n
    matched = {c for pair in pairs for c in pair}
    unmatched = [c for c in range(size) if c not in matched]
    rng = np.random.default_rng(0)
    options = math.perm(size // 2, len(pairs)) * 2 ** len(pairs) * math.factorial(len(unmatched))
    exhaustive = n * options <= 4096
    best: tuple[int, int, PairBasis] | None = None

    def consider(
        bit: int, bases: Sequence[int], flips: Sequence[bool], rest: Sequence[int]
    ) -> None:
        nonlocal best
        perm = [0] * size
        for (i, j), base, flip in zip(pairs, bases, flips, strict=True):
            lo, hi = (j, i) if flip else (i, j)
            perm[lo], perm[hi] = base, base | (1 << bit)
        for c, y in zip(unmatched, rest, strict=True):
            perm[c] = y
        gates = synthesize_permutation(tuple(perm), n)
        key = (_cnot_cost(gates), len(gates))
        if best is None or key < best[:2]:
            slot_of = {base: k for k, base in enumerate(bases)}
            best = (*key, PairBasis(gates=tuple(gates), pair_bit=bit, slot_of=slot_of))

    for bit in range(n):
        free = [x for x in range(size) if not (x >> bit) & 1]
        if exhaustive:
            for bases in itertools.permutations(free, len(pairs)):
                spare = [y for b in free if b not in bases for y in (b, b | (1 << bit))]
                for flips in itertools.product((False, True), repeat=len(pairs)):
                    for rest in itertools.permutations(spare):
                        consider(bit, bases, flips, rest)
        else:
            for _ in range(4096 // n):
                order = [int(x) for x in rng.permutation(free)]
                spares = [y for b in order[len(pairs) :] for y in (b, b | (1 << bit))]
                consider(
                    bit,
                    order[: len(pairs)],
                    [bool(v) for v in rng.integers(0, 2, size=len(pairs))],
                    [int(y) for y in rng.permutation(spares)],
                )
    assert best is not None
    return best[2]


# --- one copy: Alice's phases, Bob's basis change, the decoded outcome -------------


def alice_phases(inst: Instance, tw: Twirl) -> NDArray[np.float64]:
    """Alice's diagonal for one copy: phase π·[σ_c = −1] + (π/2)·pad(u) at u = π(c),
    where σ is her signs on a signal copy and the all-agree string on a test copy."""
    phases = np.zeros(1 << inst.n)
    for c in range(1 << inst.n):
        u = tw.relabel(c)
        negative = not tw.test and inst.signs[c] < 0
        phases[u] = (math.pi if negative else 0.0) + math.pi / 2 * tw.pad(u)
    return phases


def bob_basis_change(qubits: list[Qubit], tw: Twirl, basis: PairBasis) -> None:
    """Undo the pad (a diagonal Clifford) and the relabelling (X^t, then a CNOT
    circuit for A⁻¹), then rotate M's pair basis onto the computational basis."""
    for k, a in enumerate(tw.lin):  # pad⁻¹: S^(−lin_k) per qubit ...
        power = (-a) % 4
        if power == 1:
            qubits[k].apply(Gate.S)
        elif power == 2:
            qubits[k].apply(Gate.Z)
        elif power == 3:
            qubits[k].apply(Gate.RZ, -math.pi / 2)  # S† up to a global phase
    for k, j in tw.quad:  # ... and a CZ per quadratic term
        qubits[k].cz(qubits[j])
    for k in range(len(qubits)):
        if (tw.shift >> k) & 1:
            qubits[k].apply(Gate.X)
    for control, target in linear_inverse_cnots(tw.rows, len(qubits)):
        qubits[control].cnot(qubits[target])
    for controls, target in basis.gates:
        apply_mct(qubits, controls, target)
    qubits[basis.pair_bit].apply(Gate.H)


def decode(inst: Instance, tw: Twirl, basis: PairBasis, alice_bits: int, bob_bits: int) -> int:
    """The copy's outcome Y: s_i·s_j (or ±1 under noise) for the matched pair Bob's
    measurement landed on, corrected by Alice's X outcomes; 0 off the matching."""
    slot = basis.slot_of.get(bob_bits & ~(1 << basis.pair_bit))
    if slot is None:
        return 0
    i, j = inst.pairs[slot]
    flips = (bob_bits >> basis.pair_bit) + _parity(alice_bits & (tw.relabel(i) ^ tw.relabel(j)))
    return -1 if flips & 1 else 1


# --- the confidence interval -------------------------------------------------------


def confidence_interval(
    signal_sum: int, test_sum: int, copies: int, alpha: float, q: float, delta: float
) -> tuple[float, float] | None:
    """The set of f with |D(f)| <= τ(f), as its hull [lo, hi]; None if empty.

    Per copy, ξ = q·Y·[signal] − (1−q)(1−2f)·Y·[test] has conditional mean 0 for the
    true f whatever the source did, |ξ| <= R(f) = max(q, (1−q)|1−2f|), and conditional
    variance at most q(1−q)·α·(q + (1−q)(1−2f)²) — the copy lands on a matched pair
    with probability exactly α, because the twirl is fresh. Freedman's inequality then
    gives P(|D(f)| >= τ(f)) <= δ with τ = R·L/3 + √((R·L/3)² + 2·V·L), L = ln(2/δ).
    """
    f = np.linspace(0.0, 1.0, 2001)
    g = 1.0 - 2.0 * f
    big_l = math.log(2.0 / delta)
    var = copies * q * (1.0 - q) * alpha * (q + (1.0 - q) * g**2)
    reach = np.maximum(q, (1.0 - q) * np.abs(g)) * big_l / 3.0
    tau = reach + np.sqrt(reach**2 + 2.0 * var * big_l)
    inside = np.abs(q * signal_sum - (1.0 - q) * g * test_sum) <= tau
    if not inside.any():
        return None
    step = float(f[1] - f[0])  # widen by one grid step so discretization never under-covers
    return max(0.0, float(f[inside].min()) - step), min(1.0, float(f[inside].max()) + step)


# --- the application ------------------------------------------------------------------


class TieAudit:
    """The TieAudit application. Run configuration keys, all optional:

    - `copies` (256): protocol copies, each consuming `n` pairs and `n` bits;
    - `n` (3): qubits per side, P = 2^n slots, from 2 to 6;
    - `matched_fraction` (1.0), `conflict_fraction` (0.25) and `instance_seed` (0):
      the instance both roles derive (Alice uses only its signs, Bob only its
      matching, plus the true f for scoring);
    - `test_fraction` (0.5): share of copies that are hidden tests;
    - `delta` (0.05): the probability the verified interval may miss f;
    - `eps` (0.2): the interval half-width that counts as success.
    """

    name = "tie_audit"

    def __init__(
        self,
        copies: int = 256,
        n: int = 3,
        min_fidelity: float = _ADVANTAGE_FIDELITY,
        eps: float = 0.2,
        delta: float = 0.05,
    ) -> None:
        self.copies = copies
        self.n = n
        self.min_fidelity = min_fidelity
        self.eps = eps
        self.delta = delta

    def roles(self) -> list[Role]:
        return ["alice", "bob"]  # alice holds the signs, bob audits them

    def _demand(self) -> Demand:
        # Measured on arrival with no classical wait: no latency budget to meet.
        return Demand(min_fidelity=self.min_fidelity, purpose="keep")

    def run(self, host: Host, role: Role, cfg: dict[str, object]) -> AppOutcome:
        n = cfg_int(cfg, "n", self.n)
        if not 2 <= n <= _MAX_N:
            raise ValueError(f"tie_audit needs 2 <= n <= {_MAX_N} (P = 2^n slots), got {n}")
        copies = max(1, cfg_int(cfg, "copies", self.copies))
        test_fraction = cfg_float(cfg, "test_fraction", 0.5)
        if not 0.0 < test_fraction < 1.0:
            raise ValueError(f"tie_audit needs 0 < test_fraction < 1, got {test_fraction}")
        instance = make_instance(
            n,
            cfg_float(cfg, "matched_fraction", 1.0),
            cfg_float(cfg, "conflict_fraction", 0.25),
            cfg_int(cfg, "instance_seed", 0),
        )
        if role == "alice":
            return self._alice(host, instance, copies, test_fraction)
        eps = cfg_float(cfg, "eps", self.eps)
        delta = cfg_float(cfg, "delta", self.delta)
        return self._bob(host, instance, copies, test_fraction, eps, delta)

    def _alice(self, host: Host, inst: Instance, copies: int, q: float) -> AppOutcome:
        epr, cls = host.epr_socket("bob"), host.classical_socket("bob")
        n = inst.n
        # Stands in for the pre-shared randomness: per copy a label, an affine map
        # and a pad. It travels before any pair is requested.
        setup_seed = int(host.rng.integers(0, 2**63))
        cls.send(setup_seed.to_bytes(8, "little"))
        secrets = np.random.default_rng(setup_seed)
        for _ in range(copies):
            tw = draw_twirl(secrets, n, q)
            halves = [h.qubit for h in epr.request(n, self._demand())]
            qubits = [qb for qb in halves if qb is not None]
            assert len(qubits) == n
            apply_diagonal(qubits, alice_phases(inst, tw), fixed=True)
            bits = sum(qb.measure(Basis.X) << k for k, qb in enumerate(qubits))
            cls.send(bits.to_bytes((n + 7) // 8, "little"))
        lo, hi, utility, success = _VERDICT.unpack(cls.recv())
        return AppOutcome(
            role="alice",
            success=success,
            utility=utility,
            payload={"copies": copies, "n": n, "online_bits": copies * n, "lo": lo, "hi": hi},
        )

    def _bob(
        self, host: Host, inst: Instance, copies: int, q: float, eps: float, delta: float
    ) -> AppOutcome:
        epr, cls = host.epr_socket("alice"), host.classical_socket("alice")
        n = inst.n
        secrets = np.random.default_rng(int.from_bytes(cls.recv(), "little"))
        basis = pair_basis(n, inst.pairs)
        records: list[tuple[Twirl, int]] = []  # (twirl, Bob's measured bits)
        for _ in range(copies):
            tw = draw_twirl(secrets, n, q)
            halves = [h.qubit for h in epr.request(n, self._demand())]
            qubits = [qb for qb in halves if qb is not None]
            assert len(qubits) == n
            bob_basis_change(qubits, tw, basis)  # measured on arrival
            records.append((tw, sum(qb.measure(Basis.Z) << k for k, qb in enumerate(qubits))))
        signal_sum = test_sum = 0
        for tw, bob_bits in records:  # no feed-forward: Alice's bits are only read now
            y = decode(inst, tw, basis, int.from_bytes(cls.recv(), "little"), bob_bits)
            if tw.test:
                test_sum += y
            else:
                signal_sum += y
        n_test = sum(1 for tw, _ in records if tw.test)
        alpha = inst.matched_fraction
        interval = confidence_interval(signal_sum, test_sum, copies, alpha, q, delta)
        lo, hi = interval if interval is not None else (0.0, 1.0)
        covered = interval is not None and lo - 1e-9 <= inst.f <= hi + 1e-9
        utility = max(0.0, 1.0 - (hi - lo)) if covered else 0.0
        success = covered and (hi - lo) / 2 <= eps
        cls.send(_VERDICT.pack(lo, hi, utility, success))
        n_signal = copies - n_test
        signal = test_sum / (alpha * n_test) if n_test else None
        f_hat = None
        if signal and signal > 0 and n_signal:
            f_hat = (1.0 - signal_sum / (alpha * n_signal * signal)) / 2.0
        return AppOutcome(
            role="bob",
            success=success,
            utility=utility,
            payload={
                "copies": copies,
                "n": n,
                "online_bits": copies * n,
                "test_copies": n_test,
                "matched_fraction": alpha,
                "signal": signal,  # estimate of the twirled attenuation η
                "f": inst.f,
                "f_hat": f_hat,
                "lo": lo,
                "hi": hi,
                "covered": covered,
                "delta": delta,
            },
        )

