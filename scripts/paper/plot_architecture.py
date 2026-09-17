#!/usr/bin/env python3
"""Figure 1: the layered architecture, and where the two frozen contracts sit.

A diagram rather than the tabular this replaces, because the point being made is
about *direction* — who is allowed to depend on whom, and which two interfaces
are held still so that everything else can move. A stack of table rows cannot
show that; arrows can.

    python scripts/paper/plot_architecture.py --out figures/architecture.pdf
"""

from __future__ import annotations

import argparse

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

INK, MUTED, GHOST = "#0b0b0b", "#52514e", "#c9c9c4"
FROZEN = "#2a78d6"
SURFACE = "#f2f2ef"

# (label, detail, frozen?)
LAYERS = [
    ("harness", "run(app $\\times$ backend $\\times$ policy $\\times$ topology), CLI", False),
    ("metrics / characterize", "traces $\\rightarrow$ report, signatures, curves", False),
    ("trace", "versioned event schema", True),
    ("apps", "applications, written once", False),
    ("api", "the portable shim", True),
    ("backends, policies", "reference $|$ sequence $|$ netsquid", False),
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="architecture.pdf")
    args = ap.parse_args()

    plt.rcParams.update({"font.family": "serif", "font.size": 8})
    fig, ax = plt.subplots(figsize=(3.4, 2.5))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, len(LAYERS) * 1.15 + 0.3)
    ax.axis("off")

    h = 1.0
    for i, (name, detail, frozen) in enumerate(LAYERS):
        y = (len(LAYERS) - 1 - i) * 1.15 + 0.3
        ax.add_patch(FancyBboxPatch(
            (0.15, y), 7.5, h, boxstyle="round,pad=0.02,rounding_size=0.08",
            linewidth=1.2 if frozen else 0.7,
            edgecolor=FROZEN if frozen else MUTED,
            facecolor="white" if frozen else SURFACE, zorder=2,
        ))
        ax.text(0.42, y + h * 0.62, name, fontsize=8, color=INK,
                family="monospace", va="center", zorder=3)
        ax.text(0.42, y + h * 0.24, detail, fontsize=6.3, color=MUTED,
                va="center", zorder=3)
        if frozen:
            ax.text(7.75, y + h / 2, "frozen\ncontract", fontsize=6.2,
                    color=FROZEN, va="center", ha="left", linespacing=1.2, zorder=3)

    # Dependency direction: everything above depends downward, never upward.
    ax.add_patch(FancyArrowPatch(
        (0.0, len(LAYERS) * 1.15 + 0.1), (0.0, 0.35),
        arrowstyle="-|>", mutation_scale=9, linewidth=0.9,
        color=MUTED, shrinkA=0, shrinkB=0, zorder=1,
    ))
    ax.text(-0.42, len(LAYERS) * 1.15 / 2, "depends on", fontsize=6.5, color=MUTED,
            rotation=90, va="center", ha="center")

    fig.tight_layout(pad=0.2)
    fig.savefig(args.out, bbox_inches="tight")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
