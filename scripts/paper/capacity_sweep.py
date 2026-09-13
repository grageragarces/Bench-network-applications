#!/usr/bin/env python3
"""Capacity-sensitivity sweep for the ranking-inversion result (Sec. VIII-C).

The headline result (Table IV) is reported at one operating point, capacity =
110 pairs/s ("moderate overload"). This script sweeps capacity, holding the
tenant mixes, link fidelity, and coherence time fixed at their Table IV values,
and reports at each point which policy wins each workload mix. It exists so the
capacity-sensitivity claim in the paper text is regenerable from source, the
same way the demand-signature curves and cross-backend table are.

    python scripts/paper/capacity_sweep.py > scripts/paper/data/capacity_sweep.txt
"""

from __future__ import annotations

from qnetbench.contention import (
    COHERENCE_TIME,
    LINK_FIDELITY,
    best_policy,
    default_mixes,
    ranking_experiment,
)


def main() -> None:
    mixes = default_mixes()
    capacities = list(range(10, 171, 5)) + [200, 250, 300, 400]

    header = f"{'capacity':>8}  {'dh_fifo':>7} {'dh_ff':>7} {'dh_edf':>7} {'dh_win':>15}  {'fh_fifo':>7} {'fh_ff':>7} {'fh_edf':>7} {'fh_win':>15}  inversion"
    print(header)
    print("-" * len(header))
    for cap in capacities:
        exp = ranking_experiment(mixes, capacity=cap, link_fidelity=LINK_FIDELITY, coherence_time=COHERENCE_TIME)
        dh, fh = exp["deadline_heavy"], exp["fidelity_heavy"]
        dh_win, fh_win = best_policy(dh), best_policy(fh)
        print(
            f"{cap:>8}  {dh['fifo'].aggregate_utility:>7.3f} {dh['fidelity_first'].aggregate_utility:>7.3f} "
            f"{dh['edf'].aggregate_utility:>7.3f} {dh_win:>15}  "
            f"{fh['fifo'].aggregate_utility:>7.3f} {fh['fidelity_first'].aggregate_utility:>7.3f} "
            f"{fh['edf'].aggregate_utility:>7.3f} {fh_win:>15}  {dh_win != fh_win}"
        )


if __name__ == "__main__":
    main()
