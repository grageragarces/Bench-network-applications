#!/usr/bin/env python3
"""Coherence-time sensitivity sweep for the ranking-inversion result (Sec. VIII-C).

Companion to capacity_sweep.py: holds the tenant populations, link fidelity and
capacity fixed at their Table IV values and sweeps coherence time instead, to
check whether the inversion is a property of the chosen operating point or of
contention itself. Replicated over independent arrival draws, with ties reported
as ties.

    python scripts/paper/coherence_sweep.py > scripts/paper/data/coherence_sweep.txt
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _sweep_common import draws, point  # noqa: E402

from qnetbench.contention import CAPACITY, DRAWS, N_REQUESTS  # noqa: E402


def main() -> None:
    populations = draws()
    coherence_times = [
        0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14, 0.15,
        0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.75, 1.00, 2.00, 5.00, 50.00,
    ]

    print(
        f"coherence sweep at capacity {CAPACITY:.0f} pairs/s: {DRAWS} independent arrival "
        f"draws, {N_REQUESTS} requests/tenant."
    )
    print("winner = every policy tied for the top score; support = draws agreeing.\n")
    header = (
        f"{'coherence_s':>11}  {'dh winner':>14} {'sup':>5}  {'fh winner':>14} {'sup':>5}  "
        f"{'inversion':>9}  {'dh rate':>7} {'fh rate':>7}"
    )
    print(header)
    print("-" * len(header))
    for ct in coherence_times:
        modal, inv, rate = point(populations, capacity=CAPACITY, coherence_time=ct)
        (dh_w, dh_n), (fh_w, fh_n) = modal["deadline_heavy"], modal["fidelity_heavy"]
        print(
            f"{ct:>11.2f}  {dh_w:>14} {dh_n:>3}/{DRAWS:<2} {fh_w:>14} {fh_n:>3}/{DRAWS:<2} "
            f"{inv:>6}/{DRAWS:<2}  {rate['deadline_heavy']:>7.3f} {rate['fidelity_heavy']:>7.3f}"
        )


if __name__ == "__main__":
    main()
