#!/usr/bin/env python3
"""Plot demand-signature curves from `qnetbench characterize --out DIR`.

Reads the per-app signature + curve JSON written by the characterize command and
draws two overlaid figures — utility vs delivered fidelity, and utility vs pair age —
so the applications' fidelity-sensitivity and staleness-tolerance can be compared.

    qnetbench characterize --out sig/       # write the curve data
    python scripts/plot_curves.py sig/      # -> curves.png

Requires the optional viz extra: pip install "qnetbench[viz]".
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless; write a file, don't open a window
import matplotlib.pyplot as plt  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("indir", help="directory written by `qnetbench characterize --out`")
    parser.add_argument("--out", default="curves.png", help="output image (default: curves.png)")
    args = parser.parse_args()

    files = sorted(Path(args.indir).glob("*.json"))
    if not files:
        raise SystemExit(
            f"no per-app JSON in {args.indir!r}; run "
            f"`qnetbench characterize --out {args.indir}` first"
        )

    fig, (ax_fid, ax_stale) = plt.subplots(1, 2, figsize=(13, 5))
    for path in files:
        data = json.loads(path.read_text())
        app = data["signature"]["app"]
        fid = data["fidelity_curve"]
        stale = data["staleness_curve"]
        ax_fid.plot(
            [row["delivered_fidelity"] for row in fid],
            [row["utility"] for row in fid],
            marker="o",
            markersize=3,
            label=app,
        )
        ax_stale.plot(
            [row["pair_age_s"] * 1e3 for row in stale],
            [row["utility"] for row in stale],
            marker="o",
            markersize=3,
            label=app,
        )

    ax_fid.set(xlabel="delivered fidelity", ylabel="utility", title="Fidelity sensitivity")
    ax_stale.set(xlabel="pair age (ms)", ylabel="utility", title="Staleness tolerance")
    for ax in (ax_fid, ax_stale):
        ax.set_ylim(-0.02, 1.02)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(args.out, dpi=120)
    print(f"wrote {args.out} ({len(files)} apps)")


if __name__ == "__main__":
    main()
