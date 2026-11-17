"""The walkthrough figure: what happens to one entanglement request.

Four lifelines, top to bottom, with what each step writes to the trace. It separates what qnetbench
does from what a simulator does by showing where the simulator appears: one box, once.

    python scripts/paper/plot_walkthrough.py --out DIR
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

INK, MUTED, GHOST = "#0b0b0b", "#52514e", "#c9c9c4"
FROZEN = "#2a78d6"
SWAP = "#eb6834"
SURFACE = "#f2f2ef"
OUT = Path(".")

LANES = {"app": 0.12, "engine": 0.40, "link": 0.655, "supply": 0.89}
TOP = 0.885
BOTTOM = 0.205

# (from, to, label, y, trace event or None)
STEPS = [
    ("app", "engine", "epr.request(n, Demand)", 0.835, "ent_requested"),
    ("engine", "link", "both sides have asked", 0.745, None),
    ("link", "link", "policy orders\nthe queue", 0.675, None),
    ("link", "supply", "next pair?", 0.595, None),
    ("supply", "link", "delay, fidelity", 0.53, None),
    ("link", "engine", "pair ready", 0.465, None),
    ("engine", "app", "handle: qubit, fidelity,\nlatency, age, violations", 0.385,
     "ent_delivered, contract_violation"),
    ("app", "engine", "gates, measure, classical", 0.30, "measurement, classical_msg"),
    ("app", "engine", "AppOutcome", 0.235, "app_outcome"),
]


def _box(ax, x, y, w, h, text, *, edge=GHOST, face="white", size=5.8, weight="normal", dashed=False):
    ax.add_patch(
        FancyBboxPatch(
            (x - w / 2, y - h / 2),
            w,
            h,
            boxstyle="round,pad=0.004,rounding_size=0.012",
            fc=face,
            ec=edge,
            lw=0.9,
            ls=(0, (3, 2)) if dashed else "-",
            zorder=3,
        )
    )
    ax.text(x, y, text, ha="center", va="center", fontsize=size, color=INK, weight=weight, zorder=4,
            linespacing=1.15)


def main() -> None:
    global OUT
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("."), help="directory for the figure")
    OUT = parser.parse_args().out
    plt.rcParams.update({"font.family": "serif"})
    fig, ax = plt.subplots(figsize=(3.5, 4.3))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    _box(ax, LANES["app"], 0.945, 0.2, 0.06, "Application", face=SURFACE, weight="bold")
    _box(ax, LANES["engine"], 0.945, 0.2, 0.06, "Execution\nengine", face=SURFACE, weight="bold")
    _box(ax, LANES["link"], 0.945, 0.2, 0.06, "Link server\nand policy", face=SURFACE, weight="bold")
    _box(ax, LANES["supply"], 0.945, 0.2, 0.06, "Supply", edge=SWAP, weight="bold", dashed=True)
    ax.text(LANES["supply"], 0.898, "analytic, SeQUeNCe\nor NetSquid", ha="center", va="top",
            fontsize=4.9, color=MUTED, linespacing=1.1)

    for name, x in LANES.items():
        top = 0.862 if name == "supply" else TOP + 0.03
        low = 0.50 if name == "supply" else (0.44 if name == "link" else BOTTOM)
        ax.plot([x, x], [low, top], color=GHOST, lw=0.7, zorder=1)

    # The frozen API contract sits between the application and the engine.
    api_x = (LANES["app"] + LANES["engine"]) / 2 + 0.01
    ax.plot([api_x, api_x], [BOTTOM, TOP + 0.005], color=FROZEN, lw=0.9, ls=(0, (1, 1.5)), zorder=2)
    ax.text(api_x, TOP + 0.012, "api", ha="center", va="bottom", fontsize=5.2, color=FROZEN,
            weight="bold")

    for start, end, label, y, event in STEPS:
        if start == end:
            ax.text(LANES[start], y, label, ha="center", va="center", fontsize=5.4, color=INK,
                    linespacing=1.1, zorder=5,
                    bbox=dict(boxstyle="round,pad=0.25", fc=SURFACE, ec=GHOST, lw=0.6))
            continue
        ax.add_patch(
            FancyArrowPatch(
                (LANES[start], y),
                (LANES[end], y),
                arrowstyle="-|>",
                mutation_scale=5.5,
                lw=0.7,
                color=INK,
                shrinkA=0,
                shrinkB=0,
                zorder=4,
            )
        )
        middle = (LANES[start] + LANES[end]) / 2
        ax.text(middle, y + 0.009, label, ha="center", va="bottom", fontsize=5.0, color=INK,
                linespacing=1.05, zorder=5,
                bbox=dict(boxstyle="square,pad=0.08", fc="white", ec="none", alpha=0.85))
        if event:
            ax.text(LANES["engine"] + 0.022, y - 0.011, event, ha="left", va="top", fontsize=4.9,
                    color=FROZEN, family="monospace", zorder=5)

    # Everything written goes to the versioned trace, and everything downstream reads that.
    _box(ax, 0.40, 0.135, 0.62, 0.05, "Trace: one versioned JSONL file per run", edge=FROZEN, size=5.6)
    ax.add_patch(
        FancyArrowPatch((LANES["engine"], BOTTOM), (LANES["engine"], 0.162), arrowstyle="-|>",
                        mutation_scale=5.5, lw=0.7, color=INK, zorder=4)
    )
    for x, text in ((0.17, "Report"), (0.40, "Signature"), (0.63, "Curves"), (0.87, "Third-party\ntools")):
        _box(ax, x, 0.045, 0.2, 0.055, text, size=5.8)
    for x in (0.17, 0.40, 0.63):
        ax.add_patch(
            FancyArrowPatch((x, 0.11), (x, 0.074), arrowstyle="-|>", mutation_scale=5, lw=0.6,
                            color=MUTED, zorder=2)
        )
    ax.add_patch(
        FancyArrowPatch((0.71, 0.13), (0.87, 0.074), arrowstyle="-|>", mutation_scale=5, lw=0.6,
                        color=MUTED, connectionstyle="arc3,rad=-0.15", zorder=2)
    )

    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "walkthrough.pdf", bbox_inches="tight", pad_inches=0.02)
    fig.savefig(OUT / "walkthrough.png", bbox_inches="tight", pad_inches=0.02, dpi=260)
    print(f"wrote {OUT / 'walkthrough.pdf'}")


if __name__ == "__main__":
    main()
