"""Where does agreement across supplies stop?

With no memory noise every application is identical on all three supplies, on every seed, because
nothing an application computes depends on when its pair arrived. Held-qubit decay is the one thing
that lets timing reach the physics. So this runs each two-role application alone, at one link description,
with memory on, and asks which of them now give different answers on different supplies.

    .venv/bin/python scripts/paper/timing_reaches_physics.py --supplies reference,sequence
    .venv-ns/bin/python scripts/paper/timing_reaches_physics.py --supplies netsquid,netsquid-exponential
    .venv/bin/python scripts/paper/timing_reaches_physics.py --merge
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import statistics
from pathlib import Path

from qnetbench.apps import available_apps, get_app
from qnetbench.characterize.provenance import write_atomic
from qnetbench.tenancy import ExecutionModel, TenantSpec, application_utility, run_tenants
from qnetbench.topology import LinkModel

DATA = Path(__file__).parent / "data"
RATE = 153.0
COHERENCE = 0.01
SEEDS = 16
# NetSquid's source has drawn random gaps by default since release 1.1.0. The results here were
# produced with its fixed-period source, so "netsquid" is pinned to it.
OPTIONS: dict[str, dict] = {
    "netsquid": {"timing": "fixed"},
    "netsquid-exponential": {"timing": "exponential"},
}
LINK = LinkModel(1.0 / RATE, 0.99, 0.0)
SUPPLIES = ("reference", "sequence", "netsquid", "netsquid-exponential")


def _sensitive(args: argparse.Namespace) -> None:
    """More seeds on the applications that hold state, where 16 cannot resolve the gaps."""
    apps = args.apps.split(",")
    work = [
        (s, a, COHERENCE, seed)
        for s in args.supplies.split(",")
        for a in apps
        for seed in range(args.seeds)
    ]
    results: dict = {}
    with multiprocessing.Pool() as pool:
        for supply, app, _, _, value in pool.map(_cell, work, chunksize=4):
            results.setdefault(supply, {}).setdefault(app, []).append(value)
    name = args.supplies.split(",")[0]
    (DATA / f"timing_sensitive_{name}.json").write_text(json.dumps(results))
    print("wrote", args.supplies)


def _merge_sensitive() -> None:
    results: dict = {}
    for path in sorted(DATA.glob("timing_sensitive_*.json")):
        results.update(json.loads(path.read_text()))
    supplies = [s for s in SUPPLIES if s in results]
    apps = sorted(next(iter(results.values())))
    seeds = len(results[supplies[0]][apps[0]])
    lines = [
        f"Applications that hold state, {seeds} seeds, dephasing at T2 = {COHERENCE:g} s, {RATE:g} pairs/s.",
        "Reference has cv 1.0, SeQUeNCe 0.70, NetSquid 0, and NetSquid random about 1.",
        "",
        f"{'application':20}" + "".join(f"{s[:13]:>15}" for s in supplies) + f"{'max gap':>9}{'z':>7}",
    ]
    for app in apps:
        means = {s: statistics.fmean(results[s][app]) for s in supplies}
        high = max(supplies, key=lambda s: means[s])
        low = min(supplies, key=lambda s: means[s])
        diff = [a - b for a, b in zip(results[high][app], results[low][app], strict=True)]
        gap = statistics.fmean(diff)
        se = statistics.stdev(diff) / math.sqrt(len(diff))
        cells = "".join(
            f"{f'{means[s]:.3f}±{statistics.stdev(results[s][app]) / math.sqrt(seeds):.3f}':>15}"
            for s in supplies
        )
        lines.append(f"{app:20}{cells}{gap:>9.3f}{gap / se if se else 0:>7.1f}")
    text = "\n".join(lines) + "\n"
    write_atomic(DATA / "timing_sensitive.txt", text)
    print(text)


def _cell(args: tuple[str, str, float, int]) -> tuple[str, str, float, int, float]:
    supply, app, coherence, seed = args
    run = run_tenants(
        [TenantSpec("t", app)],
        seed=seed,
        link=LINK,
        classical_latency=1e-3,
        coherence_time=coherence,
        model=ExecutionModel(arrivals="closed_loop"),
        supply=supply.split("-")[0],
        supply_window=12.0,
        supply_options=OPTIONS.get(supply),
    )
    return supply, app, coherence, seed, application_utility(run.traces["t"])


def merge() -> None:
    results: dict = {}
    for path in sorted(DATA.glob("timing_reaches_physics_*.json")):
        for supply, by_app in json.loads(path.read_text()).items():
            results[supply] = by_app
    supplies = [s for s in SUPPLIES if s in results]
    apps = sorted(next(iter(results.values())))
    lines = [
        f"Each two-role application alone, {RATE:g} pairs/s, link fidelity 0.99, classical delay 1 ms,",
        f"{SEEDS} seeds. Mean utility with no memory decay, then with dephasing at T2 = {COHERENCE:g} s.",
        "z is the largest gap between supplies with decay, over its paired standard error.",
        "",
        f"{'application':24}{'no decay':>10}" + "".join(f"{s[:9]:>11}" for s in supplies)
        + f"{'max gap':>9}{'z':>7}",
    ]
    moved = 0
    for app in apps:
        none = {s: results[s][app]["inf"] for s in supplies}
        flat = all(none[s] == none[supplies[0]] for s in supplies)
        decayed = {s: results[s][app][str(COHERENCE)] for s in supplies}
        means = {s: statistics.fmean(decayed[s]) for s in supplies}
        high = max(supplies, key=lambda s: means[s])
        low = min(supplies, key=lambda s: means[s])
        diff = [a - b for a, b in zip(decayed[high], decayed[low], strict=True)]
        gap = statistics.fmean(diff)
        se = statistics.stdev(diff) / math.sqrt(len(diff))
        z = gap / se if se > 0 else 0.0
        moved += z > 3.0
        baseline = f"{statistics.fmean(none[supplies[0]]):.3f}{'' if flat else '*'}"
        cells = "".join(f"{means[s]:>11.3f}" for s in supplies)
        lines.append(f"{app:24}{baseline:>10}{cells}{gap:>9.3f}{z:>7.1f}")
    lines += [
        "",
        f"{len(apps)} applications: {moved} differ between supplies by more than 3 s.e. with decay.",
        "A * would mark an application whose no-decay value differed between supplies.",
    ]
    text = "\n".join(lines) + "\n"
    write_atomic(DATA / "timing_reaches_physics.txt", text)
    print(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--supplies", default="")
    parser.add_argument("--merge", action="store_true")
    parser.add_argument("--apps", default="")
    parser.add_argument("--seeds", type=int, default=128)
    parser.add_argument("--merge-sensitive", action="store_true")
    args = parser.parse_args()
    if args.merge:
        merge()
        return
    if args.merge_sensitive:
        _merge_sensitive()
        return
    if args.apps:
        _sensitive(args)
        return
    apps = [a for a in available_apps() if len(get_app(a).roles()) == 2]
    supplies = args.supplies.split(",")
    work = [
        (s, a, c, seed)
        for s in supplies
        for a in apps
        for c in (math.inf, COHERENCE)
        for seed in range(SEEDS)
    ]
    results: dict = {}
    with multiprocessing.Pool() as pool:
        for supply, app, coherence, _, value in pool.map(_cell, work, chunksize=4):
            key = "inf" if math.isinf(coherence) else str(coherence)
            results.setdefault(supply, {}).setdefault(app, {}).setdefault(key, []).append(value)
    (DATA / f"timing_reaches_physics_{supplies[0]}.json").write_text(json.dumps(results))
    print("wrote", supplies)


if __name__ == "__main__":
    main()
