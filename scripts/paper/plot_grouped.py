"""Fidelity and staleness curves grouped by demand class, and the signature table in the same grouping.

One order and one colour per class across the figure and the table, line styles and markers that
survive greyscale, and every application named, with exact overlaps reported.

    python scripts/paper/plot_grouped.py --out DIR

Writes DIR/curves-grouped.pdf (and .png, for looking at) and scripts/paper/data/table-grouped.tex.
The palette passes the colourblind checks: slots 1-6 of the reference palette, adjacent pairs.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "scripts/paper/data"
OUT = Path(".")

# One order everywhere. Each class keeps one colour across the figure and both tables.
CLASSES: dict[str, tuple[str, list[str]]] = {
    "key distribution / correlation": (
        "2a78d6",
        ["qkd", "bb84", "b92", "six_state", "multihop_qkd", "chsh", "clock_sync",
         "shared_randomness"],
    ),
    "secure computation": ("eb6834", ["bqc", "verified_bqc", "oblivious_transfer"]),
    "distributed gates": (
        "1baf7a",
        ["distributed_gate", "dqc_ghz4", "dqc_qft4", "dqc_random4", "position_verification"],
    ),
    "teleportation / relay": ("eda100", ["teleportation", "heralded_teleport",
                                         "entanglement_swap"]),
    "distillation": ("e87ba4", ["distillation", "distilled_gate"]),
    "multipartite GHZ": (
        "008300",
        ["anonymous_transmission", "byzantine_agreement", "secret_sharing",
         "threshold_secret_sharing", "conference_key", "leader_election"],
    ),
}
STYLES = ["-", (0, (4, 1.5)), (0, (1, 1)), (0, (4, 1, 1, 1)), (0, (7, 1.5)), (0, (2, 1)),
          (0, (4, 1, 1, 1, 1, 1)), (0, (1, 2))]
MARKERS = ["o", "s", "^", "v", "D", "P", "X", "*"]
GHOST = "#d8d8d3"
INK, MUTED = "#0b0b0b", "#52514e"
ROWS = (("fidelity_curve", "delivered_fidelity"), ("staleness_curve", "pair_age_s"))


def _curve(data: dict, row: int) -> tuple[list[float], list[float]]:
    rows = data[ROWS[row][0]]
    return [r[ROWS[row][1]] for r in rows], [r["utility"] for r in rows]


def _overlaps(data: dict[str, dict]) -> dict[int, list[tuple[str, str]]]:
    """Pairs of applications whose whole curve is identical, for each row."""
    found: dict[int, list[tuple[str, str]]] = {0: [], 1: []}
    names = sorted(data)
    for row in (0, 1):
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                if _curve(data[a], row) == _curve(data[b], row):
                    found[row].append((a, b))
    return found


def plot(data: dict[str, dict], overlaps: dict[int, list[tuple[str, str]]]) -> None:
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.size": 7,
            "axes.edgecolor": MUTED,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "axes.labelcolor": INK,
        }
    )
    classes = list(CLASSES)
    fig, axes = plt.subplots(2, len(classes), figsize=(7.1, 4.45), sharey=True, sharex="row")
    for col, name in enumerate(classes):
        hue, members = CLASSES[name]
        color = f"#{hue}"
        # Identical on both rows means one curve: draw it once and name both in the legend.
        same = {b: a for a, b in overlaps[0] if (a, b) in overlaps[1] and b in members}
        names = {a: f"{a} =\n{b}" for b, a in same.items()}
        members = [a for a in members if a in data and a not in same]
        others = [a for a in data if a not in members and a not in same]
        for row in (0, 1):
            ax = axes[row][col]
            for app in others:
                ax.plot(*_curve(data[app], row), color=GHOST, lw=0.5, zorder=1)
            if name == "distillation" and row == 0:
                ax.plot([0.5, 1.0], [0.5, 1.0], color=MUTED, lw=0.5, ls=(0, (3, 2)), zorder=3)
                ax.annotate("$u = F$", xy=(0.79, 0.79), xytext=(5, -10),
                            textcoords="offset points", fontsize=5.6, color=MUTED, zorder=4)
            for index, app in enumerate(members):
                xs, ys = _curve(data[app], row)
                ax.plot(
                    xs, ys, color=color, lw=0.95, ls=STYLES[index], marker=MARKERS[index],
                    markersize=2.6, markevery=(index % 4, 4), markerfacecolor="white",
                    markeredgewidth=0.6, zorder=2 + index * 0.01,
                )
            ax.grid(True, color=MUTED, alpha=0.15, lw=0.4)
            ax.set_axisbelow(True)
            ax.set_ylim(-0.04, 1.06)
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
            if row == 0:
                ax.set_title(name.replace(" / ", " /\n").replace(" ", "\n", 1)
                             if " / " not in name and " " in name
                             else name.replace(" / ", " /\n"),
                             fontsize=6.8, color=INK, pad=4, linespacing=1.15)
                ax.set_xlim(0.49, 1.01)
                ax.set_xticks([0.5, 0.75, 1.0])
            else:
                ax.set_xlim(-0.0002, 0.005)
                ax.set_xticks([0, 0.0025, 0.005])
            if col:
                ax.tick_params(labelleft=False, labelbottom=False)
            else:
                ax.set_xticklabels(["0.5", "0.75", "1.0"] if row == 0 else ["0", "2.5", "5"])
        handles = [
            Line2D([], [], color=color, lw=0.95, ls=STYLES[i], marker=MARKERS[i], markersize=2.6,
                   markerfacecolor="white", markeredgewidth=0.6,
                   label=names.get(app, app).replace("_", " "))
            for i, app in enumerate(members)
        ]
        axes[1][col].legend(
            handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.31), frameon=False,
            fontsize=4.7, handlelength=2.6, labelspacing=0.3, borderaxespad=0.0, ncol=1,
        )
    axes[0][0].set_ylabel("utility", color=INK)
    axes[1][0].set_ylabel("utility", color=INK)
    axes[0][0].set_xlabel("delivered fidelity", color=INK, labelpad=2)
    axes[1][0].set_xlabel("pair age (ms)", color=INK, labelpad=2)
    fig.subplots_adjust(left=0.07, right=0.995, top=0.9, bottom=0.3, wspace=0.16, hspace=0.34)
    out = OUT
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / "curves-grouped.pdf", bbox_inches="tight")
    fig.savefig(out / "curves-grouped.png", bbox_inches="tight", dpi=220)
    print(f"wrote {out / 'curves-grouped.pdf'}")


def _rgb(hue: str) -> str:
    return ",".join(f"{int(hue[i : i + 2], 16) / 255:.3f}" for i in (0, 2, 4))


def table() -> None:
    """The signature table in the figure's order, with a coloured heading for each class."""
    source = (DATA / "table.tex").read_text()
    head, _, rest = source.partition("\\midrule\n")
    body, _, tail = rest.partition("\\bottomrule")
    rows = {}
    for line in body.splitlines():
        match = re.match(r"\\code\{(.+?)\}", line)
        if match:
            rows[match.group(1).replace("\\_", "_")] = line
    columns = len(re.search(r"\\begin\{tabular\}\{(.*?)\}\n", head).group(1).replace("@{}", ""))
    out = [head + "\\midrule"]
    used = set()
    for name, (hue, members) in CLASSES.items():
        out.append(
            f"\\multicolumn{{{columns}}}{{@{{}}l}}{{\\textcolor[rgb]{{{_rgb(hue)}}}"
            f"{{\\rule{{1.2ex}}{{1.2ex}}}}\\ \\emph{{{name}}}}} \\\\"
        )
        for app in members:
            out.append(rows[app])
            used.add(app)
    missing = set(rows) - used
    assert not missing, f"applications in no class: {missing}"
    out.append("\\bottomrule" + tail.rstrip("\n"))
    target = DATA
    (target / "table-grouped.tex").write_text("\n".join(out) + "\n")
    print(f"wrote scripts/paper/data/table-grouped.tex ({len(used)} applications)")


def main() -> None:
    global OUT
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("."), help="directory for the figure")
    OUT = parser.parse_args().out
    data = {}
    for path in sorted(DATA.glob("*.json")):
        if path.name == "manifest.json":
            continue
        loaded = json.loads(path.read_text())
        if "signature" in loaded:
            data[loaded["signature"]["app"]] = loaded
    overlaps = _overlaps(data)
    for row, pairs in overlaps.items():
        print(f"row {row} identical curves: {pairs}")
    plot(data, overlaps)
    table()


if __name__ == "__main__":
    main()
