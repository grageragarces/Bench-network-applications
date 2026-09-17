#!/usr/bin/env python3
"""Capacity-sensitivity sweep for the ranking-inversion result (Sec. VIII-C).

The headline result (Table IV) is reported at one operating point, capacity =
160 pairs/s against 167 req/s of aggregate demand ("moderate overload"). This
script sweeps capacity, holding the tenant populations, link fidelity, and
coherence time fixed, and reports at each point which policy wins each workload
mix.

Every point is evaluated over independent arrival draws rather than one
realisation, and winners are reported as sets so that a tie is visible as a tie.
Both matter here: tenants of the same application used to share an arrival
sequence and a start time, and several operating points have two policies on
exactly the same score.

    python scripts/paper/capacity_sweep.py > scripts/paper/data/capacity_sweep.txt
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _sweep_common import draws, point  # noqa: E402

from qnetbench.contention import DRAWS, N_REQUESTS  # noqa: E402


def main() -> None:
    populations = draws()
    capacities = list(range(20, 201, 10)) + [250, 300, 400]

    print(
        f"capacity sweep: {DRAWS} independent arrival draws, {N_REQUESTS} requests/tenant, "
        f"5 tenants at one request per 30 ms (167 req/s aggregate demand)."
    )
    print("winner = every policy tied for the top score; support = draws agreeing.\n")
    header = (
        f"{'capacity':>8}  {'dh winner':>14} {'sup':>5}  {'fh winner':>14} {'sup':>5}  "
        f"{'inversion':>9}  {'dh rate':>7} {'fh rate':>7}"
    )
    print(header)
    print("-" * len(header))
    for cap in capacities:
        modal, inv, rate = point(populations, capacity=float(cap))
        (dh_w, dh_n), (fh_w, fh_n) = modal["deadline_heavy"], modal["fidelity_heavy"]
        print(
            f"{cap:>8}  {dh_w:>14} {dh_n:>3}/{DRAWS:<2} {fh_w:>14} {fh_n:>3}/{DRAWS:<2} "
            f"{inv:>6}/{DRAWS:<2}  {rate['deadline_heavy']:>7.3f} {rate['fidelity_heavy']:>7.3f}"
        )


if __name__ == "__main__":
    main()
