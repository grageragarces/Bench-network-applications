#!/usr/bin/env python3
"""Figure 2: which policy wins depends on the workload, as a picture not a table.

Contract satisfaction against link capacity, for three scheduling policies, on
each of the two workload mixes. The visual point: EDF is the top line on the left
panel and the bottom line on the right, over the same capacities.

Two panels rather than one chart with two y-axes, and one shared satisfaction
scale, so the two mixes are read against the same ruler. Each policy keeps its
colour, dash pattern and marker across both panels, so identity survives both
greyscale printing and colour-vision deficiency; the dash and marker are doing
real work here, not decoration.

    python scripts/paper/plot_inversion.py --out figures/inversion.pdf
"""

from __future__ import annotations

import argparse
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from _sweep_common import draws  # noqa: E402

from qnetbench.contention import (  # noqa: E402
    CAPACITY,
    COHERENCE_TIME,
    LINK_FIDELITY,
    ranking_experiment,
)

# Categorical slots 1-3 of the validated default palette, assigned in fixed order
# and never cycled. Colour follows the policy, not its rank in either panel.
STYLE = {
    "fifo": ("#2a78d6", "-", "o", "FIFO"),
    "fidelity_first": ("#eb6834", "--", "s", "fidelity-first"),
    "edf": ("#1baf7a", "-.", "^", "EDF"),
}
PANELS = (
    ("deadline_heavy", "Deadline-heavy mix"),
    ("fidelity_heavy", "Fidelity-heavy mix"),
)
CAPACITIES = list(range(60, 221, 20))
INK, MUTED = "#0b0b0b", "#52514e"


def measure() -> dict[str, dict[str, tuple[list[float], list[float]]]]:
    """mean and sd of contract satisfaction per mix, policy and capacity."""
    populations = draws()
    out: dict[str, dict[str, tuple[list[float], list[float]]]] = {
        mix: {p: ([], []) for p in STYLE} for mix, _ in PANELS
    }
    for cap in CAPACITIES:
        acc: dict[str, dict[str, list[float]]] = {
            mix: {p: [] for p in STYLE} for mix, _ in PANELS
        }
        for mixes in populations:
            exp = ranking_experiment(
                mixes,
                capacity=float(cap),
                link_fidelity=LINK_FIDELITY,
                coherence_time=COHERENCE_TIME,
            )
            for mix, _ in PANELS:
                for policy in STYLE:
                    acc[mix][policy].append(exp[mix][policy].aggregate_utility)
        for mix, _ in PANELS:
            for policy in STYLE:
                vals = acc[mix][policy]
                out[mix][policy][0].append(st.mean(vals))
                out[mix][policy][1].append(st.stdev(vals))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="inversion.pdf")
    args = ap.parse_args()

    data = measure()
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "DejaVu Serif"],
        "font.size": 8,
        "axes.edgecolor": MUTED,
        "axes.labelcolor": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
    })
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.7), sharey=True)

    for ax, (mix, title) in zip(axes, PANELS, strict=True):
        # The band where the two mixes pick different winners on every draw.
        # Named in the figure legend rather than annotated inside the axes.
        ax.axvspan(120, 160, color="#0b0b0b", alpha=0.07, lw=0, zorder=0)
        ax.axvline(CAPACITY, color=MUTED, lw=0.8, ls=":", zorder=1)
        for policy, (colour, dash, marker, label) in STYLE.items():
            mean, sd = data[mix][policy]
            ax.fill_between(
                CAPACITIES,
                [m - s for m, s in zip(mean, sd, strict=True)],
                [m + s for m, s in zip(mean, sd, strict=True)],
                color=colour, alpha=0.12, lw=0, zorder=2,
            )
            # FIFO sits under fidelity-first and slightly wider: on the
            # deadline-heavy mix the two are exactly equal, and a reader should
            # see two coincident lines rather than one line of ambiguous colour.
            wide = policy == "fifo"
            ax.plot(
                CAPACITIES, mean, color=colour, ls=dash, marker=marker,
                markersize=4.5 if wide else 3.2, lw=2.6 if wide else 1.5,
                label=label, zorder=3 if wide else 4,
                markeredgecolor="white", markeredgewidth=0.4,
                alpha=0.9 if wide else 1.0,
            )
        ax.set_title(title, fontsize=8.5, color=INK, pad=6)
        ax.set_xlabel("link capacity (pairs/s)")
        ax.grid(True, color=MUTED, alpha=0.18, lw=0.5)
        ax.set_axisbelow(True)
        ax.set_ylim(-0.03, 1.06)
        ax.set_xlim(min(CAPACITIES) - 5, max(CAPACITIES) + 5)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)

    axes[0].set_ylabel("contract satisfaction")
    # No per-line labels: on both panels the series converge or cross, so a label
    # at any single x collides with its neighbours. Identity is carried by the
    # figure-level legend plus each policy's dash pattern and marker, which also
    # keeps the figure readable in greyscale and under colour-vision deficiency.
    handles, labels = axes[0].get_legend_handles_labels()
    # The shaded band and the operating-point rule are keyed in the same legend
    # as the policies, so every mark in the figure is named in one place. The
    # swatch carries more alpha than the band: a legend patch is small, and at
    # the band's own alpha it would read as blank paper.
    handles += [
        Patch(facecolor="#0b0b0b", alpha=0.18, edgecolor=MUTED, lw=0.4),
        Line2D([], [], color=MUTED, lw=0.8, ls=":"),
    ]
    labels += ["all 32 draws disagree", f"operating point ({CAPACITY:.0f} pairs/s)"]
    fig.legend(
        handles, labels, frameon=False, fontsize=7.5, labelcolor=INK,
        loc="upper center", ncol=5, handlelength=2.6,
        bbox_to_anchor=(0.5, 1.12), columnspacing=1.6,
    )
    fig.tight_layout()
    fig.subplots_adjust(right=0.88)
    fig.savefig(args.out, bbox_inches="tight")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
