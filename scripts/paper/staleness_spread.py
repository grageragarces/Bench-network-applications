"""How far apart are applications' staleness half-lives, from unrounded values?

Two measures, both read from the characterization JSON in `scripts/paper/data/`:

- absolute: the age at which utility falls to half its fresh-pair value (`staleness_halflife`);
- floor-relative: the age at which it falls halfway from its fresh-pair value to its own asymptotic floor
  (`staleness_halflife_range`).

Where the mean curve never crosses but individual seeds do, the table marks the entry with a tilde and gives the
median over the seeds that cross (`staleness_halflife_seed_median`). The ratio is reported with those entries and
without them, so the dependence on that choice is visible. For the floor-relative measure only the mean-curve value
is stored, so applications without one are listed.

    python scripts/paper/staleness_spread.py > scripts/paper/data/staleness_spread.txt
"""

from __future__ import annotations

import json
import pathlib

DATA = pathlib.Path(__file__).resolve().parents[2] / "scripts/paper/data"


def _load() -> dict[str, dict]:
    rows = {}
    for path in sorted(DATA.glob("*.json")):
        if path.stem == "manifest":
            continue
        try:
            rows[path.stem] = json.loads(path.read_text())["signature"]
        except (KeyError, ValueError):
            continue
    return rows


def _spread(values: dict[str, float]) -> tuple[tuple[str, float], tuple[str, float], float]:
    ordered = sorted(values.items(), key=lambda item: item[1])
    return ordered[0], ordered[-1], ordered[-1][1] / ordered[0][1]


def main() -> None:
    rows = _load()
    print(f"{len(rows)} applications read from scripts/paper/data/*.json\n")

    absolute_mean = {n: s["staleness_halflife"] for n, s in rows.items() if s.get("staleness_halflife")}
    absolute_all = dict(absolute_mean)
    for n, s in rows.items():
        if n not in absolute_all and s.get("staleness_halflife_seed_median"):
            absolute_all[n] = s["staleness_halflife_seed_median"]
    floor_mean = {n: s["staleness_halflife_range"] for n, s in rows.items() if s.get("staleness_halflife_range")}

    print(f"{'measure':<46}{'n':>3}  {'lowest':<30}{'highest':<30}{'ratio':>8}")
    for label, values in (
        ("absolute, mean curve only", absolute_mean),
        ("absolute, with seed medians (the table)", absolute_all),
        ("floor-relative, mean curve", floor_mean),
    ):
        low, high, ratio = _spread(values)
        print(
            f"{label:<46}{len(values):>3}  {low[0] + f' {low[1]:.3g}':<30}{high[0] + f' {high[1]:.3g}':<30}{ratio:>8.1f}"
        )

    missing = sorted(n for n, s in rows.items() if n in absolute_all and n not in floor_mean)
    none_at_all = sorted(n for n in rows if n not in absolute_all)
    print(f"\nin the absolute set but without a floor-relative value: {', '.join(missing) or 'none'}")
    print(f"no staleness half-life of either kind: {', '.join(none_at_all) or 'none'}")

    print("\nper application, seconds (absolute, floor-relative):")
    for n in sorted(rows, key=lambda name: absolute_all.get(name, float("inf"))):
        a, f = absolute_all.get(n), floor_mean.get(n)
        print(f"  {n:<26}{f'{a:.4g}' if a else '-':>12}{f'{f:.4g}' if f else '-':>12}")


if __name__ == "__main__":
    main()
