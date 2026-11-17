"""Are the two largest deviations in `analytic_validation.py` real, or chance among 60 cells?

Each is rerun on seeds the first pass did not use. Scoring the same seeds again would
just reproduce the deviation.

    python scripts/paper/analytic_outliers.py
"""

from __future__ import annotations

import math
import multiprocessing
import statistics

from analytic_validation import CASES, _measure

CHECKS = [("bqc", "P(s=e)", 0.99), ("distillation", "F out", 0.70)]
FIRST_SEED = 1000
SEEDS = 512


def main() -> None:
    with multiprocessing.Pool() as pool:
        for app, quantity, fidelity in CHECKS:
            index = next(
                i for i, c in enumerate(CASES) if c[0] == app and c[1] == quantity
            )
            work = [(index, fidelity, s) for s in range(FIRST_SEED, FIRST_SEED + SEEDS)]
            values = [v for _, _, v in pool.map(_measure, work)]
            mean = statistics.fmean(values)
            se = statistics.stdev(values) / math.sqrt(len(values))
            expected = CASES[index][3](fidelity)
            print(
                f"{app:14}{quantity:12} F={fidelity:.2f}  predicted {expected:.4f}  "
                f"measured {mean:.4f} ± {se:.4f}  z {(mean - expected) / se:+.2f}  ({SEEDS} new seeds)"
            )


if __name__ == "__main__":
    main()
