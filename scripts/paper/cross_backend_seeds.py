"""Merge the per-seed cross-backend results into one table.

Each result file holds one seed's utilities, from `scripts/paper/cross_backend.py`, which runs one seed
at a time. This says how far backends differ once seed noise is accounted for: a
backend gap counts as real only if it stands out from the seed-to-seed spread.

Produce the per-seed files with no fidelity spread, so every supply delivers the same fidelity, named
`<name>-<seed>.json` (files sharing a seed are merged):

    .venv/bin/python    scripts/paper/cross_backend.py --backends reference,sequence --seed S \
        --fidelity-std 0 --out scripts/paper/data/cross_backend_seeds/ref_seq-S.json
    .venv-ns/bin/python scripts/paper/cross_backend.py --backends netsquid --seed S \
        --fidelity-std 0 --out scripts/paper/data/cross_backend_seeds/ns-S.json

for S from 0 to 31, then:

    python scripts/paper/cross_backend_seeds.py scripts/paper/data/cross_backend_seeds
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

from qnetbench.characterize.provenance import write_atomic

OUT = Path(__file__).parent / "data" / "cross_backend_seeds.txt"
BACKENDS = ("reference", "sequence", "netsquid")


def main() -> None:
    directory = Path(sys.argv[1])
    by_seed: dict[int, dict[str, dict]] = {}
    for path in sorted(directory.glob("*.json")):
        seed = int(path.stem.rsplit("-", 1)[1])
        for app, row in json.loads(path.read_text()).items():
            by_seed.setdefault(seed, {}).setdefault(app, {}).update(row)
    seeds = sorted(by_seed)
    apps = sorted(next(iter(by_seed.values())))

    lines = [
        f"{len(seeds)} seeds, same fidelity spread (none) on all supplies. Mean utility per backend,",
        "the largest gap between backends, and that gap in paired standard errors across seeds.",
        "",
        f"{'application':26}" + "".join(f"{b:>11}" for b in BACKENDS)
        + f"{'max gap':>9}{'s.e.':>8}{'z':>7}{'exact':>7}",
    ]
    exact = close = supply_bound = errors = 0
    for app in apps:
        values: dict[str, list[float]] = {b: [] for b in BACKENDS}
        failed = False
        for seed in seeds:
            for backend in BACKENDS:
                cell = by_seed[seed][app].get(backend, {})
                if "utility" in cell:
                    values[backend].append(cell["utility"])
                else:
                    failed = True
        if failed:
            errors += 1
        usable = [b for b in BACKENDS if len(values[b]) == len(seeds)]
        means = {b: statistics.fmean(values[b]) for b in usable}
        first = max(usable, key=lambda b: means[b])
        last = min(usable, key=lambda b: means[b])
        gaps = [a - b for a, b in zip(values[first], values[last], strict=True)]
        gap = statistics.fmean(gaps)
        se = statistics.stdev(gaps) / math.sqrt(len(gaps))
        z = gap / se if se > 0 else 0.0
        identical = all(
            max(by_seed[s][app][b]["utility"] for b in usable)
            - min(by_seed[s][app][b]["utility"] for b in usable)
            <= 1e-6
            for s in seeds
        )
        exact += identical
        close += gap <= 0.02
        supply_bound += z > 3.0
        cells = "".join(f"{means[b]:>11.4f}" if b in means else f"{'-':>11}" for b in BACKENDS)
        lines.append(
            f"{app:26}{cells}{gap:>9.4f}{se:>8.4f}{z:>7.1f}{'yes' if identical else 'no':>7}"
        )
    lines += [
        "",
        f"{len(apps)} applications: {exact} identical on every seed, {close} with a mean gap within "
        f"0.02, {supply_bound} with a gap above 3 s.e., {errors} with a backend error.",
    ]
    text = "\n".join(lines) + "\n"
    write_atomic(OUT, text)
    print(text)


if __name__ == "__main__":
    main()
