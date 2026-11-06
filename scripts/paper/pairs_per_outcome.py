#!/usr/bin/env python3
"""Does the fidelity requirement follow the number of pairs an outcome depends on?

Section VI argues that what sets an application's fidelity threshold is not its
party count but how many entangled pairs a single outcome is conditioned on. The
evidence there is three GHZ protocols and two applications that break the
party-count correlation, which is suggestive rather than measured.

The circuit catalog supplies a controlled family for the same question. A mirror
circuit succeeds only if every teleported gate in it succeeded, so its outcome is
conditioned on every pair it consumed, and the family's sizes sweep that count
while holding the structure fixed. Plotting the measured F_1/2 against pairs per
outcome turns the claim into a curve that can be checked.

    python scripts/paper/pairs_per_outcome.py > scripts/paper/data/pairs_per_outcome.txt
"""

from __future__ import annotations

import math

from qnetbench.apps import get_app
from qnetbench.characterize import characterize_trace
from qnetbench.characterize.curves import _topology_for
from qnetbench.harness.runner import run_once
from qnetbench.metrics.report import compute_report
from qnetbench.topology import LinkModel

# Dense where the all-correct crossings live (0.88-0.99), coarse below.
GRID = [0.50, 0.60, 0.70, 0.75, 0.80, 0.84, 0.88, 0.90,
        0.92, 0.94, 0.95, 0.96, 0.97, 0.98, 0.99, 1.00]


def _curves(app: str, seeds: int) -> tuple[list[float], list[float]]:
    """Mean all-correct rate and mean restored-qubit fraction, per grid point.

    Both are swept together because the paper needs both: the conjunction model
    is about the all-correct event, while the suite's published F_1/2 is
    computed from the averaged restored-qubit fraction.
    """
    roles = get_app(app).roles()
    succ: list[float] = []
    util: list[float] = []
    for f in GRID:
        link = LinkModel(attempt_latency=1e-3, link_fidelity=f, fidelity_std=0.0)
        topo = _topology_for(roles, link)
        reps = [compute_report(run_once(app, seed=s, topology=topo)) for s in range(seeds)]
        succ.append(sum(r.app_success for r in reps) / len(reps))
        util.append(sum(r.app_utility for r in reps) / len(reps))
    return succ, util


def _crossing(ys: list[float]) -> float | None:
    """Fidelity at which the curve first reaches the midpoint of its own range."""
    level = (min(ys) + max(ys)) / 2
    for i in range(len(GRID) - 1):
        if ys[i] <= level <= ys[i + 1] and ys[i + 1] != ys[i]:
            span = GRID[i + 1] - GRID[i]
            return GRID[i] + span * (level - ys[i]) / (ys[i + 1] - ys[i])
    return None

# All six catalog families. An earlier version fitted only the first four,
# which was never stated in the paper and looked like selection.
FAMILIES = ("dqc_ghz", "dqc_qft", "dqc_random", "dqc_graph", "dqc_iqp", "dqc_hea")
SIZES = (4, 5, 6, 7, 8, 9, 10)
SEEDS = 32  # matches Section VI-A and run rule R3


def pairs_per_outcome(app: str) -> int:
    """Entanglement requests per run. A mirror circuit reports one outcome, so
    every pair it consumes is a pair that outcome depends on."""
    from qnetbench.trace.events import EntanglementRequested

    events = run_once(app, seed=0)
    return sum(e.n for e in events if isinstance(e, EntanglementRequested))


def main() -> None:
    print("Fidelity threshold against the number of pairs one outcome depends on.")
    print(f"Mirror-circuit families at sizes {SIZES[0]}-{SIZES[-1]}, "
          f"{SEEDS} seeds per sweep point.\n")
    print("F_1/2(all-correct) is the crossing of the rate at which a whole run is")
    print("correct -- the event the conjunction model describes. F_1/2(restored) is")
    print("the crossing of the averaged restored-qubit fraction, which is what the")
    print("suite publishes as F_1/2 and what Table II reports.\n")
    header = (f"{'application':<18} {'qubits':>6} {'pairs/outcome':>14} "
              f"{'F_1/2(all-corr)':>16} {'F_1/2(restored)':>16} {'parties':>8}")
    print(header)
    print("-" * len(header))
    pts_succ: list[tuple[str, int, float]] = []
    pts_util: list[tuple[str, int, float]] = []
    for family in FAMILIES:
        for size in SIZES:
            app = f"{family}{size}"
            try:
                k = pairs_per_outcome(app)
                succ, util = _curves(app, SEEDS)
                trace = characterize_trace(run_once(app, seed=0))
            except Exception as exc:
                print(f"{app:<18} {size:>6} {type(exc).__name__:>14}")
                continue
            cs, cu = _crossing(succ), _crossing(util)
            print(f"{app:<18} {size:>6} {k:>14} "
                  f"{(f'{cs:.3f}' if cs is not None else '---'):>16} "
                  f"{(f'{cu:.3f}' if cu is not None else '---'):>16} {trace.n_parties:>8}")
            if k > 0 and cs is not None:
                pts_succ.append((family, k, cs))
            if k > 0 and cu is not None:
                pts_util.append((family, k, cu))

    if len(pts_succ) >= 3:
        print("\n" + "=" * 72)
        print("SCORED ON THE ALL-CORRECT EVENT (what the conjunction model is about)")
        print("=" * 72)
        _report(pts_succ)
    if len(pts_util) >= 3:
        print("\n" + "=" * 72)
        print("SCORED ON THE AVERAGED RESTORED-QUBIT FRACTION (the published F_1/2)")
        print("=" * 72)
        _report(pts_util)


def _ols(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Slope, standard error of the slope, and R^2 for y = a + b x."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0 or n < 3:
        return float("nan"), float("nan"), float("nan")
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
    a = my - b * mx
    sse = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys, strict=True))
    sst = sum((y - my) ** 2 for y in ys)
    se = math.sqrt(sse / (n - 2) / sxx)
    return b, se, (1 - sse / sst if sst else float("nan"))


def _report(points: list[tuple[str, int, float]]) -> None:
    """A per-pair success model predicts F_1/2 rising with k: if one outcome
    needs k pairs each good with probability p(F), holding success fixed makes
    p^k constant, so the tolerable infidelity 1 - F_1/2 should fall as k^-1.

    The fit must be done WITHIN families. Families differ in how errors
    propagate, and the family with the largest k also has the highest
    thresholds, so a pooled regression confounds the dependence on k with the
    difference between families. Both are reported; only the within-family
    figure supports a claim about the mechanism.
    """
    fams: dict[str, list[tuple[float, float]]] = {}
    for fam, k, f in points:
        fams.setdefault(fam, []).append((math.log(k), math.log(max(1e-6, 1 - f))))

    print("\nPer-family fits (structure held fixed):")
    print(f"  {'family':<12}{'n':>3}{'slope':>9}{'se':>8}{'R^2':>7}   95% CI")
    for fam in sorted(fams):
        pts = fams[fam]
        b, se, r2 = _ols([x for x, _ in pts], [y for _, y in pts])
        if se == se:  # not NaN
            lo, hi = b - 2.57 * se, b + 2.57 * se
            print(f"  {fam:<12}{len(pts):>3}{b:>+9.3f}{se:>8.3f}{r2:>7.2f}   [{lo:+.2f}, {hi:+.2f}]")

    # Fixed effects: centre within family, then pool the deviations.
    dev: list[tuple[float, float]] = []
    for pts in fams.values():
        if len(pts) < 2:
            continue
        mx = sum(x for x, _ in pts) / len(pts)
        my = sum(y for _, y in pts) / len(pts)
        dev += [(x - mx, y - my) for x, y in pts]
    sxx = sum(dx * dx for dx, _ in dev)
    b_fe = sum(dx * dy for dx, dy in dev) / sxx
    dof = len(dev) - len(fams) - 1
    se_fe = math.sqrt(sum((dy - b_fe * dx) ** 2 for dx, dy in dev) / dof / sxx)

    xs = [math.log(k) for _, k, _ in points]
    ys = [math.log(max(1e-6, 1 - f)) for _, _, f in points]
    b_p, se_p, r2_p = _ols(xs, ys)

    ks = [k for _, k, _ in points]
    lo_pt = min(points, key=lambda t: t[1])
    hi_pt = max(points, key=lambda t: t[1])
    print(f"\n{len(points)} instances, {len(fams)} families, {SEEDS} seeds per point.")
    print(f"  pairs per outcome spans {min(ks)}-{max(ks)}")
    print(f"  F_1/2 at fewest pairs ({lo_pt[1]}): {lo_pt[2]:.3f}")
    print(f"  F_1/2 at most pairs   ({hi_pt[1]}): {hi_pt[2]:.3f}")
    print("\n  WITHIN-FAMILY (fixed effects) -- this is the reportable figure:")
    print(f"    slope {b_fe:+.3f} +- {se_fe:.3f}"
          f"   95% CI [{b_fe - 2.06 * se_fe:+.3f}, {b_fe + 2.06 * se_fe:+.3f}]")
    print(f"    t vs  0 = {b_fe / se_fe:+.2f}   (mechanism present?)")
    print(f"    t vs -1 = {(b_fe + 1) / se_fe:+.2f}   (conjunction model k^-1?)")
    print("\n  POOLED (ignores family; CONFOUNDED, reported for transparency only):")
    print(f"    slope {b_p:+.3f} +- {se_p:.3f}   R^2 {r2_p:.3f}"
          f"   95% CI [{b_p - 2.06 * se_p:+.3f}, {b_p + 2.06 * se_p:+.3f}]")
    print(f"    t vs -1 = {(b_p + 1) / se_p:+.2f}")


if __name__ == "__main__":
    main()
