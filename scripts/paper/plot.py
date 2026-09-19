#!/usr/bin/env python3
"""Figure 1 for the paper: fidelity-sensitivity and staleness-tolerance curves.

Same data as `scripts/plot_curves.py`, but laid out for a two-column figure: a
single shared legend beneath both panels (rather than one legend per axes,
overlapping the curves), serif labels, and vector output for LaTeX.

Laid out as small multiples, one column per demand class, with the class's own
applications highlighted and every other application ghosted behind them for
scale. The paper's claim about this figure is that the classes separate, which
is a statement about where each group sits relative to the others — so each
panel shows exactly that comparison, rather than asking the reader to pick one
class out of twenty-seven overlaid curves.

Individual applications are deliberately not distinguished within a panel: which
curve is which is Table III's job, and the figure's job is the shape and spread
of each class. The exception is the handful of curves the text makes a specific
claim about -- those are labelled where they are named, because a claim the
reader is invited to check against the figure has to be findable in it. See
LABELS below; everything else stays anonymous.

    qnetbench characterize --out scripts/paper/data/    # write the curve data
    python scripts/paper/plot.py scripts/paper/data/ --out curves.pdf
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

from qnetbench.characterize import verify_run

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# Demand classes, in the order they should appear in the legend. Membership
# follows the groupings used in the Sec. V discussion and Table I's "Class /
# demand contribution" column.
CLASSES: dict[str, list[str]] = {
    "key distribution / correlation": [
        "qkd", "bb84", "b92", "six_state", "multihop_qkd", "chsh",
        "clock_sync", "shared_randomness",
    ],
    "secure computation": [
        "bqc", "verified_bqc", "oblivious_transfer",
    ],
    "distributed gates": [
        "distributed_gate", "dqc_ghz4", "dqc_qft4", "dqc_random4",
        "position_verification",
    ],
    "teleportation / relay": [
        "teleportation", "heralded_teleport", "entanglement_swap",
    ],
    "distillation": [
        "distillation", "distilled_gate",
    ],
    "multipartite GHZ": [
        "anonymous_transmission", "byzantine_agreement", "secret_sharing",
        "threshold_secret_sharing", "conference_key", "leader_election",
    ],
}

# One highlight hue, not one per class. Each panel shows a single class against
# every other application drawn in grey, and the panel title says which class it
# is, so the reader never has to tell six hues apart — which twenty-seven curves
# overlaid on two axes did require, and which is why they were illegible.
# Curves the prose names and asks the reader to see. Keyed by (class, row),
# each entry is (app, x to anchor the leader at, (x, y) for the text in AXES
# fractions). Axes fractions rather than point offsets because a panel is only
# about 79 pt wide and a name set at 4.8 pt is half of that -- offsets that look
# modest push the text straight out of the panel and into its neighbour.
LABELS: dict[tuple[str, int], list[tuple[str, float, tuple[float, float]]]] = {
    ("key distribution / correlation", 0): [("qkd", 0.60, (0.05, 0.34))],
    ("distributed gates", 0): [("dqc_random4", 0.92, (0.03, 0.26))],
    ("distillation", 0): [("distillation", 0.68, (0.03, 0.90))],
    ("multipartite GHZ", 0): [
        ("conference_key", 0.93, (0.02, 0.66)),
        ("leader_election", 0.97, (0.02, 0.40)),
    ],
    ("teleportation / relay", 1): [("heralded_teleport", 0.0026, (0.26, 0.82))],
    ("multipartite GHZ", 1): [("leader_election", 0.0010, (0.30, 0.30))],
}

HIGHLIGHT = "#2a78d6"
GHOST = "#c9c9c4"
INK, MUTED = "#0b0b0b", "#52514e"


def _xy(rows, xkey):
    key = "delivered_fidelity" if xkey == "fidelity_curve" else "pair_age_s"
    return [r[key] for r in rows], [r["utility"] for r in rows]


def _annotate(ax, data_by_app, labels, xkey):
    """Point at the curves Sec. VI-B names, with a short leader line."""
    for app, xat, (tx, ty) in labels:
        if app not in data_by_app:
            continue
        xs, ys = _xy(data_by_app[app][xkey], xkey)
        yat = min(zip(xs, ys, strict=True), key=lambda p: abs(p[0] - xat))[1]
        ax.annotate(
            app,
            xy=(xat, yat), xycoords="data",
            xytext=(tx, ty), textcoords="axes fraction",
            fontsize=5.6, color=INK, zorder=5, ha="left", va="center",
            bbox=dict(boxstyle="square,pad=0.12", fc="white", ec="none", alpha=0.85),
            arrowprops=dict(arrowstyle="-", lw=0.4, color=INK, shrinkA=1, shrinkB=1.5),
        )


def _panel(ax, data_by_app, members, xkey, others):
    """One class against the ghosted rest."""
    for app in others:
        rows = data_by_app[app][xkey]
        ax.plot(
            [r["delivered_fidelity" if xkey == "fidelity_curve" else "pair_age_s"] for r in rows],
            [r["utility"] for r in rows],
            color=GHOST, lw=0.6, zorder=1, solid_capstyle="round",
        )
    for app in members:
        rows = data_by_app[app][xkey]
        ax.plot(
            [r["delivered_fidelity" if xkey == "fidelity_curve" else "pair_age_s"] for r in rows],
            [r["utility"] for r in rows],
            color=HIGHLIGHT, lw=1.3, zorder=2, solid_capstyle="round",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("indir", help="directory written by `qnetbench characterize --out`")
    parser.add_argument("--out", default="figures/curves.pdf")
    args = parser.parse_args()

    # Refuse to plot a directory that is not exactly one finished run. Fig. 1 was
    # once drawn from a directory holding two, and nothing said so.
    verify_run(Path(args.indir))
    files = sorted(p for p in Path(args.indir).glob("*.json") if p.name != "manifest.json")
    if not files:
        raise SystemExit(
            f"no per-app JSON in {args.indir!r}; run `qnetbench characterize --out` first"
        )

    data_by_app = {}
    for path in files:
        data = json.loads(path.read_text())
        data_by_app[data["signature"]["app"]] = data

    plt.rcParams.update({
        "font.family": "serif",
        "font.size": 7,
        "axes.edgecolor": MUTED,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.labelcolor": INK,
    })

    classes = list(CLASSES)
    fig, axes = plt.subplots(
        2, len(classes), figsize=(7.1, 3.3), sharey=True, sharex="row"
    )
    for col, cls in enumerate(classes):
        members = [a for a in CLASSES[cls] if a in data_by_app]
        others = [a for a in data_by_app if a not in members]
        for row, xkey in enumerate(("fidelity_curve", "staleness_curve")):
            ax = axes[row][col]
            # The distillation claim is that its output exceeds its input above
            # F = 0.52. That is a statement about where the curve sits relative
            # to u = F, so the line has to be on the plot for the claim to be
            # checkable; without it the panel shows a rising curve like any
            # other.
            if cls == "distillation" and row == 0:
                ax.plot([0.5, 1.0], [0.5, 1.0], color=MUTED, lw=0.5, ls=(0, (3, 2)),
                        zorder=3, label="$u = F$")
                ax.annotate("$u = F$", xy=(0.79, 0.79), xytext=(6, -11),
                            textcoords="offset points", fontsize=5.6, color=MUTED, zorder=4)
            _panel(ax, data_by_app, members, xkey, others)
            _annotate(ax, data_by_app, LABELS.get((cls, row), []), xkey)
            ax.grid(True, color=MUTED, alpha=0.15, lw=0.4)
            ax.set_axisbelow(True)
            ax.set_ylim(-0.04, 1.06)
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
            if row == 0:
                ax.set_title(
                    cls.replace(" / ", "/\n").replace(" ", "\n", 1),
                    fontsize=6.8, color=INK, pad=4, linespacing=1.15,
                )
                ax.set_xlim(0.49, 1.01)
                ax.set_xticks([0.5, 0.75, 1.0])
            else:
                # The decay is over within a few ms; 10 ms was mostly flat tail.
                ax.set_xlim(-0.0002, 0.005)
                ax.set_xticks([0, 0.0025, 0.005])
            # Tick labels on the leftmost column only: every panel in a row shares
            # a scale, and repeating the labels ran the "1.0" of one panel into
            # the "0.5" of the next.
            if col:
                ax.tick_params(labelleft=False, labelbottom=False)
            else:
                ax.set_xticklabels(
                    ["0.5", "0.75", "1.0"] if row == 0 else ["0", "2.5", "5"]
                )

    axes[0][0].set_ylabel("utility", color=INK)
    axes[1][0].set_ylabel("utility", color=INK)
    axes[0][0].set_xlabel("delivered fidelity", color=INK, labelpad=2)
    axes[1][0].set_xlabel("pair age (ms)", color=INK, labelpad=2)
    fig.subplots_adjust(left=0.07, right=0.995, top=0.86, bottom=0.11, wspace=0.16, hspace=0.42)
    fig.savefig(args.out, bbox_inches="tight")
    print(f"wrote {args.out} ({len(data_by_app)} apps, {len(classes)} demand classes)")


if __name__ == "__main__":
    main()
