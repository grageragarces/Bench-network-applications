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
    # 210-240 was previously unsampled, which left the transition from
    # 'fidelity-first/FIFO tie on dh' to 'all three tie' unresolved.
    capacities = list(range(20, 251, 10)) + [300, 400]

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
    rows: list[tuple[int, str, str, int, float]] = []
    for cap in capacities:
        modal, inv, rate = point(populations, capacity=float(cap))
        (dh_w, dh_n), (fh_w, fh_n) = modal["deadline_heavy"], modal["fidelity_heavy"]
        print(
            f"{cap:>8}  {dh_w:>14} {dh_n:>3}/{DRAWS:<2} {fh_w:>14} {fh_n:>3}/{DRAWS:<2} "
            f"{inv:>6}/{DRAWS:<2}  {rate['deadline_heavy']:>7.3f} {rate['fidelity_heavy']:>7.3f}"
        )
        rows.append((cap, dh_w, fh_w, inv, rate["deadline_heavy"]))

    _emit_latex(rows)


_PRETTY = {"edf": "EDF", "ff": "fid.", "fifo": "FIFO"}


def _label(winner: str) -> str:
    """'edf/ff' -> 'EDF/fid.'; the three-way tie collapses to 'all'."""
    parts = winner.split("/")
    if len(parts) == 3:
        return "all"
    return "/".join(_PRETTY.get(p, p) for p in parts)


def _regime(dh_winner: str, min_inv: int, min_rate: float) -> str:
    """The regime label Table V's first column carries.

    Derived rather than asserted, so the label cannot disagree with the row it
    sits on. The four regimes, in the order they are tested:

    - over-prov.:  all three policies tie on the deadline-heavy mix, so there
                   is no scheduling decision left to make;
    - contended:   the mixes disagree on at least three quarters of the draws;
    - starvation:  the best policy meets under 5% of contracts, so any ordering
                   is between rates too small to mean anything;
    - draining:    everything in between, where the link is clearing the queue
                   but has not yet over-provisioned.

    Contention is tested before starvation, not after. Bands are cut where a
    *winner* changes, so one band can straddle two regimes: 100-160 runs from
    4.6% satisfaction to 81%, and testing the low end first would label the
    whole of it starvation. Disagreement on three quarters of the draws is the
    stronger signal, and it is the property the band is in the table for.
    """
    if dh_winner.count("/") == 2:
        return "over-prov."
    if min_inv >= 3 * DRAWS // 4:
        return "contended"
    if min_rate < 0.05:
        return "starvation"
    return "draining"


def _emit_latex(rows: list[tuple[int, str, str, int, float]]) -> None:
    """Write Table V's body, banded by contiguous runs of identical winners.

    Hand-summarising this table put a wrong winner or a wrong disagreement range
    in three of its five rows, because a band's winner is only constant if you
    check every point in it. Generating it removes that whole failure mode: a
    band is cut wherever either winner changes.

    The body goes to `data/capacity.tex`, which the manuscript ``\\input{}``s,
    so Table V cannot drift from the sweep the way it could while it was a hand
    copy of this function's stdout. It is also echoed to stdout so the text
    report stays self-contained. Written atomically, for the reason the README
    gives about ``>`` redirects.
    """
    bands: list[list[tuple[int, str, str, int, float]]] = []
    for row in rows:
        if bands and bands[-1][0][1] == row[1] and bands[-1][0][2] == row[2]:
            bands[-1].append(row)
        else:
            bands.append([row])

    lines = [
        "% Generated by `python scripts/paper/capacity_sweep.py`. Do not edit by hand.",
        "% Requires: booktabs (\\toprule etc.).",
        "\\begin{tabular}{@{}lccrr@{}}",
        "\\toprule",
        "Capacity & dh & fh & disagreeing & best rate \\\\",
        "\\midrule",
    ]
    for band in bands:
        caps = [r[0] for r in band]
        invs = [r[3] for r in band]
        rates = [r[4] for r in band]
        span = f"{caps[0]}" if len(caps) == 1 else f"{caps[0]}--{caps[-1]}"
        inv = (f"{min(invs)}/{DRAWS}" if min(invs) == max(invs)
               else f"{min(invs)}--{max(invs)}/{DRAWS}")
        rate = (f"{min(rates):.2f}" if abs(max(rates) - min(rates)) < 5e-3
                else f"{min(rates):.2f}--{max(rates):.2f}")
        lines.append(
            f"{span} \\emph{{({_regime(band[0][1], min(invs), min(rates))})}} "
            f"& {_label(band[0][1])} & {_label(band[0][2])} & {inv} & {rate} \\\\"
        )

    lines += ["\\bottomrule", "\\end{tabular}"]

    print("\n" + "\n".join(lines))

    out = Path(__file__).resolve().parent / "data" / "capacity.tex"
    tmp = out.with_suffix(".tex.tmp")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(out)


if __name__ == "__main__":
    main()
