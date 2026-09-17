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

from qnetbench.characterize import characterize_app, characterize_trace
from qnetbench.harness.runner import run_once

FAMILIES = ("dqc_ghz", "dqc_qft", "dqc_random", "dqc_graph")
SIZES = (4, 5, 6, 7, 8, 9, 10)
SEEDS = 16


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
    header = f"{'application':<18} {'qubits':>6} {'pairs/outcome':>14} {'F_1/2':>9} {'parties':>8}"
    print(header)
    print("-" * len(header))
    points: list[tuple[int, float]] = []
    for family in FAMILIES:
        for size in SIZES:
            app = f"{family}{size}"
            try:
                k = pairs_per_outcome(app)
                sig, _ = characterize_app(app, seeds=range(SEEDS))
                trace = characterize_trace(run_once(app, seed=0))
            except Exception as exc:
                print(f"{app:<18} {size:>6} {'—':>14} {type(exc).__name__:>9}")
                continue
            f_half = sig.fidelity_threshold
            shown = f"{f_half:9.3f}" if f_half is not None else f"{'—':>9}"
            print(f"{app:<18} {size:>6} {k:>14} {shown} {trace.n_parties:>8}")
            if f_half is not None and k > 0:
                points.append((k, f_half))

    if len(points) >= 3:
        # A per-pair success model predicts F_1/2 rising as k grows: if one
        # outcome needs k independent pairs each good with probability p(F),
        # then p must rise toward 1 as k does. Fit log(1 - F_1/2) against log k;
        # a negative slope is the signature of that mechanism.
        xs = [math.log(k) for k, _ in points]
        ys = [math.log(max(1e-6, 1 - f)) for _, f in points]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        var = sum((x - mx) ** 2 for x in xs)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / var
        ss_res = sum((y - (my + slope * (x - mx))) ** 2 for x, y in zip(xs, ys, strict=True))
        ss_tot = sum((y - my) ** 2 for y in ys)
        r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")
        lo = min(points, key=lambda t: t[0])
        hi = max(points, key=lambda t: t[0])
        print(f"\n{n} instances. Pairs per outcome spans {lo[0]}-{hi[0]}.")
        print(f"  F_1/2 at fewest pairs ({lo[0]}): {lo[1]:.3f}")
        print(f"  F_1/2 at most pairs   ({hi[0]}): {hi[1]:.3f}")
        print(f"  log(1 - F_1/2) vs log(pairs): slope {slope:+.3f}, R^2 {r2:.3f}")
        print("  (negative slope = threshold rises with pairs per outcome)")


if __name__ == "__main__":
    main()
