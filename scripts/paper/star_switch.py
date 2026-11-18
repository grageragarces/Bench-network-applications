"""The same five tenants on one shared link and on a star whose hub swaps their pairs.

On one link every tenant competes for every pair. On a star each tenant uses two of the four
leaf-to-hub links, so tenants on disjoint leaves are served at once, but an end-to-end pair waits
for the slower of two legs and for the swap to be announced. This asks whether that structure
changes which policy wins, with the tenants of the position-verification experiment:

    two position_verification tenants on (L1, L2), qkd on (L1, L3),
    distributed_gate with |+/-> inputs on (L2, L4), qkd on (L3, L4)

so L1 and L2 each carry three tenants and L3 and L4 two. Every link, on either topology, makes
160 pairs/s at fidelity 0.99, with a 1 ms classical delay. "Alone" is the two verifiers without
the other tenants, placed the same way.

    python scripts/paper/star_switch.py
"""

from __future__ import annotations

import math
import multiprocessing
import statistics
from pathlib import Path

from qnetbench.characterize.provenance import write_atomic
from qnetbench.tenancy import ExecutionModel, TenantSpec, application_utility, run_tenants
from qnetbench.topology import LinkModel

OUT = Path(__file__).parent / "data" / "star_switch.txt"
POLICIES = ("fifo", "fidelity_first", "edf")
SEEDS = 64
RATE = 160.0
TIMES = (math.inf, 0.05)
TOPOLOGIES = ("one link", "star")

TENANTS = (
    TenantSpec("pv0", "position_verification", {"rounds": 96}),
    TenantSpec("pv1", "position_verification", {"rounds": 96}),
    TenantSpec("qkd0", "qkd", {"rounds": 256}),
    TenantSpec("gates", "distributed_gate", {"reps": 64, "basis": "x"}),
    TenantSpec("qkd1", "qkd", {"rounds": 256}),
)
PLACEMENT = {
    "pv0": ("L1", "L2"),
    "pv1": ("L1", "L2"),
    "qkd0": ("L1", "L3"),
    "gates": ("L2", "L4"),
    "qkd1": ("L3", "L4"),
}
GROUPS = {"verifiers": ("pv0", "pv1"), "gates": ("gates",), "qkd": ("qkd0", "qkd1")}


def _cell(args: tuple[str, bool, float, str, int]) -> tuple[tuple, dict[str, float]]:
    topology, alone, coherence, policy, seed = args
    tenants = [t for t in TENANTS if not alone or t.name.startswith("pv")]
    run = run_tenants(
        tenants,
        seed=seed,
        arbitration=f"policy:{policy}",
        link=LinkModel(1.0 / RATE, 0.99, 0.0),
        classical_latency=1e-3,
        coherence_time=coherence,
        model=ExecutionModel(arrivals="closed_loop"),
        placement=({t.name: PLACEMENT[t.name] for t in tenants} if topology == "star" else None),
    )
    out: dict[str, float] = {}
    for group, names in GROUPS.items():
        present = [n for n in names if n in run.traces]
        if present:
            out[group] = statistics.fmean(application_utility(run.traces[n]) for n in present)
            out[group + " finish"] = max(run.traces[n][-1].t for n in present)
    return args, out


def _gap(a: list[float], b: list[float]) -> str:
    diff = [x - y for x, y in zip(a, b, strict=True)]
    se = statistics.stdev(diff) / math.sqrt(len(diff))
    mean = statistics.fmean(diff)
    return f"{mean:+.3f} ({mean / se:.1f} s.e.)" if se > 0 else "tied"


def main() -> None:
    work = [
        (topo, alone, t, p, s)
        for topo in TOPOLOGIES
        for alone in (False, True)
        for t in TIMES
        for p in POLICIES
        for s in range(SEEDS)
    ]
    with multiprocessing.Pool() as pool:
        results = dict(pool.map(_cell, work, chunksize=8))

    lines = [
        "Five tenants on one shared link and on a four-leaf star with a switch at the hub, every",
        f"link {RATE:g} pairs/s at fidelity 0.99, 1 ms classical delay, {SEEDS} seeds, closed "
        "loop.",
        "Utility and finish time (s) by group under FIFO / fidelity-first / EDF.",
    ]
    for t in TIMES:
        label = "no memory decay" if math.isinf(t) else f"held qubits dephase, T2 = {t:g} s"
        lines += [
            "",
            f"{label}",
            f"  {'topology':10}{'group':12}{'utility':>22}{'finish (s)':>24}{'EDF - FIFO':>22}",
        ]
        for topo in TOPOLOGIES:
            for alone, groups in ((True, ("verifiers",)), (False, tuple(GROUPS))):
                for group in groups:
                    u = {
                        p: [results[(topo, alone, t, p, s)][group] for s in range(SEEDS)]
                        for p in POLICIES
                    }
                    f = {
                        p: statistics.fmean(
                            results[(topo, alone, t, p, s)][group + " finish"] for s in range(SEEDS)
                        )
                        for p in POLICIES
                    }
                    name = f"{group} alone" if alone else group
                    us = " ".join(f"{statistics.fmean(v):.3f}" for v in u.values())
                    fs = " ".join(f"{v:6.2f}" for v in f.values())
                    lines.append(
                        f"  {topo:10}{name:16}{us:>18}{fs:>24}{_gap(u['edf'], u['fifo']):>22}"
                    )
    text = "\n".join(lines) + "\n"
    write_atomic(OUT, text)
    print(text)


if __name__ == "__main__":
    main()
