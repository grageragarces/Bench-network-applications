"""Teleported gates whose inputs are superpositions, so held-qubit dephasing reaches their result.

`distributed_gate` in its default basis tests computational basis states, which dephasing cannot
change, so on a shared link the policy moves its contract score but not its utility. With
`basis="x"` its inputs are |+/-> states and a data qubit that waits for its pair loses phase.
This measures whether the policy then changes what the application achieves:

1. the deadline-heavy mix (four gate tenants and one qkd tenant) on the default execution model,
   with the gates in the X basis, against coherence time;
2. two X-basis gate tenants beside three qkd tenants, closed loop, as position_mix.py does for
   position verification, against coherence time.

    python scripts/paper/xbasis_gates.py
"""

from __future__ import annotations

import math
import multiprocessing
import statistics
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from executed_contention import CLASSICAL_LATENCY, POLICIES, _specs  # noqa: E402

from qnetbench.characterize.provenance import write_atomic  # noqa: E402
from qnetbench.contention import (  # noqa: E402
    CAPACITY,
    DRAWS,
    LINK_FIDELITY,
    N_REQUESTS,
    default_mixes,
)
from qnetbench.tenancy import (  # noqa: E402
    ExecutionModel,
    TenantSpec,
    application_utility,
    contract_satisfaction,
    run_tenants,
)
from qnetbench.topology import LinkModel  # noqa: E402

OUT = Path(__file__).parent / "data" / "xbasis_gates.txt"
TIMES = (math.inf, 1.0, 0.25, 0.1, 0.05, 0.01)
SEEDS = 64


def _x(spec: TenantSpec) -> TenantSpec:
    if spec.app != "distributed_gate":
        return spec
    return replace(spec, cfg={**spec.cfg, "basis": "x"})


def _mix(args: tuple[float, str, int]) -> tuple[tuple[float, str, int], tuple[float, float]]:
    coherence, policy, draw = args
    tenants = default_mixes(N_REQUESTS, seed=draw)["deadline_heavy"]
    specs = [_x(s) for s in _specs(tenants, open_loop=False)]
    run = run_tenants(
        specs,
        seed=draw,
        arbitration=f"policy:{policy}",
        link=LinkModel(1.0 / CAPACITY, LINK_FIDELITY, 0.0),
        classical_latency=CLASSICAL_LATENCY,
        coherence_time=coherence,
        model=ExecutionModel(),
    )
    gates = [s.name for s in specs if s.app == "distributed_gate"]
    return args, (
        statistics.fmean(contract_satisfaction(run.traces[s.name]) for s in specs),
        statistics.fmean(application_utility(run.traces[g]) for g in gates),
    )


def _pair(args: tuple[float, str, int]) -> tuple[tuple[float, str, int], tuple[float, float]]:
    coherence, policy, seed = args
    tenants = [
        TenantSpec(f"g{i}", "distributed_gate", {"basis": "x", "reps": 64}) for i in range(2)
    ] + [TenantSpec(f"bg{i}", "qkd", {"rounds": 256}) for i in range(3)]
    run = run_tenants(
        tenants,
        seed=seed,
        arbitration=f"policy:{policy}",
        link=LinkModel(1.0 / CAPACITY, 0.99, 0.0),
        classical_latency=1e-3,
        coherence_time=coherence,
        model=ExecutionModel(arrivals="closed_loop"),
    )
    return args, (
        statistics.fmean(application_utility(run.traces[f"g{i}"]) for i in range(2)),
        max(run.traces[f"g{i}"][-1].t for i in range(2)),
    )


def _gap(a: list[float], b: list[float]) -> str:
    diff = [x - y for x, y in zip(a, b, strict=True)]
    se = statistics.stdev(diff) / math.sqrt(len(diff))
    mean = statistics.fmean(diff)
    return f"{mean:+.3f} ({mean / se:.1f} s.e.)" if se > 0 else "tied"


def main() -> None:
    with multiprocessing.Pool() as pool:
        mix = dict(
            pool.map(
                _mix,
                [(t, p, d) for t in TIMES for p in POLICIES for d in range(DRAWS)],
                chunksize=4,
            )
        )
        pair = dict(
            pool.map(
                _pair,
                [(t, p, s) for t in TIMES for p in POLICIES for s in range(SEEDS)],
                chunksize=8,
            )
        )

    lines = [
        "distributed_gate with X-basis inputs, so held-qubit dephasing reaches its utility.",
        "",
        "1. Deadline-heavy mix, gates in the X basis, default execution model,",
        f"   {CAPACITY:g} pairs/s, {DRAWS} draws. FIFO / fidelity-first / EDF.",
        f"{'T2 (s)':>9}{'satisfaction':>24}{'gate utility':>24}{'EDF - FIFO utility':>24}",
    ]
    for t in TIMES:
        sat = {p: [mix[(t, p, d)][0] for d in range(DRAWS)] for p in POLICIES}
        util = {p: [mix[(t, p, d)][1] for d in range(DRAWS)] for p in POLICIES}
        s = " ".join(f"{statistics.fmean(v):.3f}" for v in sat.values())
        u = " ".join(f"{statistics.fmean(v):.3f}" for v in util.values())
        lines.append(f"{t:>9g}{s:>24}{u:>24}{_gap(util['edf'], util['fifo']):>24}")

    lines += [
        "",
        f"2. Two X-basis gate tenants (64 reps) beside three qkd tenants, closed loop, "
        f"{CAPACITY:g} pairs/s, {SEEDS} seeds.",
        "   Gate utility and finish time (s), FIFO / fidelity-first / EDF.",
        f"{'T2 (s)':>9}{'gate utility':>24}{'finish time':>24}{'EDF - FIFO utility':>24}",
    ]
    for t in TIMES:
        util = {p: [pair[(t, p, s)][0] for s in range(SEEDS)] for p in POLICIES}
        fin = {p: statistics.fmean(pair[(t, p, s)][1] for s in range(SEEDS)) for p in POLICIES}
        u = " ".join(f"{statistics.fmean(v):.3f}" for v in util.values())
        f = " ".join(f"{v:6.2f}" for v in fin.values())
        lines.append(f"{t:>9g}{u:>24}{f:>24}{_gap(util['edf'], util['fifo']):>24}")
    text = "\n".join(lines) + "\n"
    write_atomic(OUT, text)
    print(text)


if __name__ == "__main__":
    main()
