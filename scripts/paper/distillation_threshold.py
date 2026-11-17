#!/usr/bin/env python3
"""Where does distillation actually start repaying its inputs?

Section VI-B reports that the protocol's output first exceeds its input at an
input fidelity of ~0.63. That number came off a three-point interpolation on the
coarse characterization grid (0.5, 0.6, 0.7 — nothing in between) with no
uncertainty attached, and it sits well above the analytic break-even.

For a Werner state of fidelity F, BBPSSW/DEJMPS recurrence gives

    F' = (F^2 + e^2) / (F^2 + 2 F e + 5 e^2),   e = (1 - F) / 3

and F' > F for every F in (1/2, 1): the theoretical threshold is exactly 1/2.
A measured threshold of 0.63 is therefore a claim that wants either a mechanism
or a retraction, and the paper currently offers neither.

This script settles it:

  * sweeps a fine grid across [0.50, 0.72], where the crossing actually lies,
    instead of interpolating across a 0.1-wide gap;
  * bootstraps over seeds to put a confidence interval on the crossing;
  * prints the analytic BBPSSW curve alongside, so any gap is visible per point
    rather than inferred from the crossing alone.

    python scripts/paper/distillation_threshold.py \
        > scripts/paper/data/distillation_threshold.txt
"""

from __future__ import annotations

import math
import random

from qnetbench.characterize.curves import _fidelity_evaluator

APP = "distillation"
# Dense where the crossing is, coarse where it is not.
GRID = [round(0.50 + 0.01 * i, 3) for i in range(23)] + [0.75, 0.80, 0.90, 1.0]
SEEDS = 64          # above the suite's 32: the crossing is the quantity of interest
BOOTSTRAP = 2000
RNG_SEED = 0


def bbpssw(f: float) -> float:
    """Output fidelity of one recurrence step on a Werner state of fidelity f."""
    e = (1.0 - f) / 3.0
    return (f * f + e * e) / (f * f + 2 * f * e + 5 * e * e)


def crossing(xs: list[float], ys: list[float]) -> float | None:
    """Where the curve y(x) first meets the identity y = x, by linear interpolation."""
    for i in range(len(xs) - 1):
        d0, d1 = ys[i] - xs[i], ys[i + 1] - xs[i + 1]
        if d0 <= 0.0 <= d1 and d1 != d0:
            return xs[i] + (xs[i + 1] - xs[i]) * (-d0) / (d1 - d0)
    return None


def main() -> None:
    evaluate = _fidelity_evaluator(APP, range(SEEDS))
    per_seed: list[list[float]] = []
    means: list[float] = []

    print("Distillation: does the output repay the input, and from where?")
    print(f"{APP}, {SEEDS} seeds per point, {BOOTSTRAP} bootstrap resamples.\n")
    print(f"{'F_in':>6} {'u_mean':>9} {'sd':>8} {'sem':>8} {'BBPSSW':>9} {'u-F':>9}")
    print("-" * 54)
    for f in GRID:
        us = evaluate(f)
        per_seed.append(us)
        n = len(us)
        mu = sum(us) / n
        means.append(mu)
        sd = math.sqrt(sum((u - mu) ** 2 for u in us) / (n - 1)) if n > 1 else 0.0
        print(f"{f:>6.3f} {mu:>9.4f} {sd:>8.3f} {sd / math.sqrt(n):>8.3f} "
              f"{bbpssw(f):>9.4f} {mu - f:>+9.4f}")

    point = crossing(GRID, means)

    rng = random.Random(RNG_SEED)
    n = SEEDS
    draws: list[float] = []
    for _ in range(BOOTSTRAP):
        idx = [rng.randrange(n) for _ in range(n)]
        ys = [sum(col[i] for i in idx) / n for col in per_seed]
        c = crossing(GRID, ys)
        if c is not None:
            draws.append(c)
    draws.sort()

    print()
    if point is None:
        print("  no crossing of u(F) = F within the swept range")
    else:
        print(f"  crossing of u(F) = F on the mean curve: F* = {point:.4f}")
    if draws:
        lo = draws[int(0.025 * len(draws))]
        hi = draws[min(int(0.975 * len(draws)), len(draws) - 1)]
        med = draws[len(draws) // 2]
        print(f"  bootstrap median F* = {med:.4f}, 95% CI [{lo:.4f}, {hi:.4f}] "
              f"({len(draws)}/{BOOTSTRAP} resamples crossed)")
        # The grid starts at F = 0.5 because below it the input pairs are
        # separable and distillation cannot help: the crossing is censored at
        # the boundary of the physical domain, not at an arbitrary grid edge.
        # An interval whose lower end sits on that boundary is therefore
        # consistent with a threshold of 1/2, not evidence against it.
        floor = min(GRID)
        if lo <= 0.5 <= hi:
            verdict = "CONSISTENT with"
        elif lo - floor < 0.01:
            verdict = "censored at the domain boundary, so CONSISTENT with"
        else:
            verdict = "EXCLUDES"
        print(f"  -> the interval is {verdict} the analytic BBPSSW threshold of 0.5")
    else:
        print("  no bootstrap resample produced a crossing")

    resid = [m - bbpssw(f) for f, m in zip(GRID, means, strict=True)]
    worst = max(zip(GRID, resid, strict=True), key=lambda t: abs(t[1]))
    print(f"\n  mean |measured - BBPSSW| over the grid: "
          f"{sum(abs(r) for r in resid) / len(resid):.4f}")
    print(f"  largest deviation: {worst[1]:+.4f} at F = {worst[0]:.3f}")


if __name__ == "__main__":
    main()
