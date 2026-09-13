#!/usr/bin/env python3
"""Figure 1 for the paper: fidelity-sensitivity and staleness-tolerance curves.

Same data as `scripts/plot_curves.py`, but laid out for a two-column figure: a
single shared legend beneath both panels (rather than one legend per axes,
overlapping the curves), serif labels, and vector output for LaTeX.

Curves are colored by demand class (the same classes the paper's own §5
discussion groups applications into: key-distribution/correlation, secure
computation, distributed gates, teleportation/relay, distillation, and
multipartite GHZ coordination) rather than by an arbitrary per-app cycle, so
that applications the text describes as behaving alike (e.g. the three 3-party
GHZ protocols) also *look* alike. Linestyle and marker vary within a class so
individual applications stay distinguishable, including in greyscale.

    qnetbench characterize --out scripts/paper/data/    # write the curve data
    python scripts/paper/plot.py scripts/paper/data/ --out curves.pdf
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

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

# Okabe-Ito colorblind-safe palette, one hue per class.
CLASS_COLORS = {
    "key distribution / correlation": "#0072B2",  # blue
    "secure computation": "#D55E00",               # vermillion
    "distributed gates": "#009E73",                # bluish green
    "teleportation / relay": "#CC79A7",             # reddish purple
    "distillation": "#E69F00",                      # orange
    "multipartite GHZ": "#56B4E9",                  # sky blue
}

# (linestyle, marker) combinations cycled within a class so members stay
# distinguishable even when two curves in the same class overlap.
STYLE_CYCLE = [
    ("-", "o"), ("--", "s"), (":", "^"), ("-.", "v"),
    ("-", "D"), ("--", "P"), (":", "*"), ("-.", "X"),
]


def _app_style(app: str) -> dict:
    for cls, members in CLASSES.items():
        if app in members:
            idx = members.index(app)
            linestyle, marker = STYLE_CYCLE[idx % len(STYLE_CYCLE)]
            return dict(color=CLASS_COLORS[cls], linestyle=linestyle, marker=marker)
    # Fallback for any app not in the taxonomy above (should not happen for
    # the shipped core suite, but keeps the script from crashing on additions).
    return dict(color="#999999", linestyle="-", marker="o")


def _legend_order(available: set[str]) -> list[str]:
    order: list[str] = []
    for members in CLASSES.values():
        order.extend(app for app in members if app in available)
    # Anything unclassified goes last, alphabetically.
    order.extend(sorted(available - set(order)))
    return order


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("indir", help="directory written by `qnetbench characterize --out`")
    parser.add_argument("--out", default="figures/curves.pdf")
    args = parser.parse_args()

    files = sorted(Path(args.indir).glob("*.json"))
    if not files:
        raise SystemExit(f"no per-app JSON in {args.indir!r}; run `qnetbench characterize --out` first")

    data_by_app = {}
    for path in files:
        data = json.loads(path.read_text())
        data_by_app[data["signature"]["app"]] = data

    plt.rcParams.update({
        "font.family": "serif",
        "font.size": 8,
        "axes.titlesize": 9,
        "axes.labelsize": 8,
        "legend.fontsize": 6.5,
    })

    fig, (ax_fid, ax_stale) = plt.subplots(1, 2, figsize=(7.1, 2.8))

    handles, labels = [], []
    for app in _legend_order(set(data_by_app)):
        data = data_by_app[app]
        style = dict(_app_style(app), markersize=2.6, linewidth=1.0)
        err_style = dict(
            ecolor=style["color"], elinewidth=0.4, capsize=1.2, capthick=0.4, alpha=0.55,
        )
        cont = ax_fid.errorbar(
            [r["delivered_fidelity"] for r in data["fidelity_curve"]],
            [r["utility"] for r in data["fidelity_curve"]],
            yerr=[r.get("utility_std", 0.0) for r in data["fidelity_curve"]],
            **style,
            **err_style,
        )
        ax_stale.errorbar(
            [r["pair_age_s"] * 1e3 for r in data["staleness_curve"]],
            [r["utility"] for r in data["staleness_curve"]],
            yerr=[r.get("utility_std", 0.0) for r in data["staleness_curve"]],
            **style,
            **err_style,
        )
        handles.append(cont.lines[0])
        labels.append(app.replace("_", r"\_") if plt.rcParams["text.usetex"] else app)

    ax_fid.set(xlabel="delivered fidelity", ylabel="utility", title="(a) Fidelity sensitivity")
    ax_stale.set(xlabel="pair age (ms)", ylabel="utility", title="(b) Staleness tolerance")
    # Half-lives span 0.01 to 5.6 ms, so a linear axis crushes the short ones — the
    # 4- and 5-party GHZ protocols decay inside the first pixel of it. symlog keeps
    # the age-0 point (which log cannot show) while giving the decade below 1 ms the
    # room it needs.
    ax_stale.set_xscale("symlog", linthresh=0.01, linscale=0.35)
    ax_stale.set_xticks([0, 0.01, 0.1, 1, 10])
    ax_stale.set_xticklabels(["0", "0.01", "0.1", "1", "10"])
    for ax in (ax_fid, ax_stale):
        ax.set_ylim(-0.03, 1.03)
        ax.grid(True, alpha=0.25, linewidth=0.5)
        ax.tick_params(labelsize=7)

    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.08),
        ncol=6,
        frameon=False,
        handlelength=1.6,
        columnspacing=1.0,
    )
    fig.tight_layout(rect=(0, 0.18, 1, 1))
    fig.savefig(args.out, bbox_inches="tight")
    print(f"wrote {args.out} ({len(files)} apps, {len(CLASSES)} demand classes)")


if __name__ == "__main__":
    main()
