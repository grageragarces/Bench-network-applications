#!/usr/bin/env python3
"""Coherence-time sensitivity sweep for the ranking-inversion result (Sec. VIII-C).

Companion to capacity_sweep.py: holds the tenant mixes, link fidelity, and
capacity fixed at their Table IV values and sweeps coherence time instead, to
check whether the inversion is a property of the chosen operating point or of
contention itself.

    python scripts/paper/coherence_sweep.py > scripts/paper/data/coherence_sweep.txt
"""

from __future__ import annotations

from qnetbench.contention import (
    CAPACITY,
    LINK_FIDELITY,
    best_policy,
    default_mixes,
    ranking_experiment,
)


def main() -> None:
    mixes = default_mixes()
    coherence_times = [
        0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14, 0.15,
        0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.75, 1.00, 2.00, 5.00, 50.00,
    ]

    header = f"{'coherence_s':>11}  {'dh_fifo':>7} {'dh_ff':>7} {'dh_edf':>7} {'dh_win':>15}  {'fh_fifo':>7} {'fh_ff':>7} {'fh_edf':>7} {'fh_win':>15}  inversion"
    print(header)
    print("-" * len(header))
    for ct in coherence_times:
        exp = ranking_experiment(mixes, capacity=CAPACITY, link_fidelity=LINK_FIDELITY, coherence_time=ct)
        dh, fh = exp["deadline_heavy"], exp["fidelity_heavy"]
        dh_win, fh_win = best_policy(dh), best_policy(fh)
        print(
            f"{ct:>11.2f}  {dh['fifo'].aggregate_utility:>7.3f} {dh['fidelity_first'].aggregate_utility:>7.3f} "
            f"{dh['edf'].aggregate_utility:>7.3f} {dh_win:>15}  "
            f"{fh['fifo'].aggregate_utility:>7.3f} {fh['fidelity_first'].aggregate_utility:>7.3f} "
            f"{fh['edf'].aggregate_utility:>7.3f} {fh_win:>15}  {dh_win != fh_win}"
        )


if __name__ == "__main__":
    main()
