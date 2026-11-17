"""How do the executed results move with the memory's coherence time?

The 0.25 s came from the queue model, where it is a constant nobody had to justify. Marchese et
al. plot delays up to 20 ms against NV dephasing and see fidelity fall by about a third over
that range, which suggests coherence times far shorter than 0.25 s on that hardware.

    python scripts/paper/coherence_sensitivity.py
"""

from __future__ import annotations

import math
import multiprocessing
import statistics
from pathlib import Path

from qnetbench.characterize.provenance import write_atomic
from qnetbench.contention import (
    LINK_FIDELITY,
    ContentionResult,
    arrival_times,
    default_mixes,
    has_inversion,
)
from qnetbench.tenancy import (
    TenantSpec,
    application_utility,
    contract_satisfaction,
    run_tenants,
)
from qnetbench.topology import LinkModel

OUT = Path(__file__).parent / "data" / "coherence_sensitivity.txt"
TIMES = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 1.0, math.inf)
POLICIES = ("fifo", "fidelity_first", "edf")
LINK = LinkModel(1.0 / 160, LINK_FIDELITY, 0.0)
REQUEST_COUNT = {"distributed_gate": "reps", "qkd": "rounds", "bqc": "depth", "chsh": "rounds"}
SENSITIVE = ("dqc_qft4", "dqc_qft4", "dqc_random4")
BACKGROUND = {"with qkd": ("qkd", {"rounds": 256}), "with gates": ("distributed_gate", {"reps": 64})}
CONTRACTS: dict[str, dict[str, object]] = {"as declared": {}, "no deadline": {"latency_budget": 1.0}}


def _default_mix(args: tuple[float, str, str, int]) -> tuple[float, str, str, int, float, float]:
    coherence, mix, policy, seed = args
    tenants = default_mixes(100, seed=seed)[mix]
    specs = [
        TenantSpec(
            f"{t.app}-{i}", t.app, {REQUEST_COUNT[t.app]: t.n_requests}, tuple(arrival_times(t))
        )
        for i, t in enumerate(tenants)
    ]
    run = run_tenants(
        specs,
        seed=seed,
        arbitration=f"policy:{policy}",
        link=LINK,
        classical_latency=1e-3,
        coherence_time=coherence,
    )
    traces = [run.traces[s.name] for s in specs]
    return (
        coherence,
        mix,
        policy,
        seed,
        statistics.fmean(contract_satisfaction(t) for t in traces),
        statistics.fmean(application_utility(t) for t in traces),
    )


def _sensitive(args: tuple[float, str, str, str, int]) -> tuple[float, str, str, str, int, float]:
    coherence, background, contract, policy, seed = args
    app, cfg = BACKGROUND[background]
    tenants = [
        TenantSpec(f"s{i}", name, demand_override=CONTRACTS[contract])
        for i, name in enumerate(SENSITIVE)
    ] + [TenantSpec(f"bg{i}", app, cfg) for i in range(2)]
    run = run_tenants(
        tenants,
        seed=seed,
        arbitration=f"policy:{policy}",
        link=LINK,
        classical_latency=1e-3,
        coherence_time=coherence,
    )
    value = statistics.fmean(application_utility(run.traces[f"s{i}"]) for i in range(3))
    return coherence, background, contract, policy, seed, value


def main() -> None:
    draws = 16
    seeds = 128
    with multiprocessing.Pool() as pool:
        defaults = pool.map(
            _default_mix,
            [
                (c, m, p, s)
                for c in TIMES
                for m in ("deadline_heavy", "fidelity_heavy")
                for p in POLICIES
                for s in range(draws)
            ],
        )
        sensitive = pool.map(
            _sensitive,
            [
                (c, b, k, p, s)
                for c in TIMES
                for b in BACKGROUND
                for k in CONTRACTS
                for p in POLICIES
                for s in range(seeds)
            ],
        )

    lines = [
        f"Agreed model, dephasing, {LINK_FIDELITY} link fidelity, 160 pairs/s, classical delay 1 ms.",
        "",
        f"The default mixes, {draws} draws: contract satisfaction, utility, and draws with no policy "
        "best on both mixes.",
        f"  {'T (s)':>7}{'mix':>16}" + "".join(f"{p:>16}" for p in POLICIES) + f"{'utility':>10}",
    ]
    for coherence in TIMES:
        disagree = 0
        for seed in range(draws):
            results = {
                mix: {
                    p: ContentionResult(
                        policy=p,
                        aggregate_utility=round(
                            next(
                                r[4]
                                for r in defaults
                                if r[0] == coherence and r[1] == mix and r[2] == p and r[3] == seed
                            ),
                            9,
                        ),
                    )
                    for p in POLICIES
                }
                for mix in ("deadline_heavy", "fidelity_heavy")
            }
            disagree += has_inversion(results)
        for mix in ("deadline_heavy", "fidelity_heavy"):
            rows = [r for r in defaults if r[0] == coherence and r[1] == mix]
            cells = "".join(
                f"{statistics.fmean(r[4] for r in rows if r[2] == p):>16.3f}" for p in POLICIES
            )
            utility = statistics.fmean(r[5] for r in rows)
            lines.append(f"  {coherence:>7g}{mix:>16}{cells}{utility:>10.3f}")
        lines.append(f"  {'':>7}{'disagree':>16}{disagree:>16} of {draws}")

    lines += [
        "",
        f"Three dqc tenants and two background tenants, {seeds} seeds: mean dqc utility, and the",
        "difference between EDF and FIFO with its paired standard error.",
        f"  {'T (s)':>7}{'background':>12}{'contract':>13}"
        + "".join(f"{p:>16}" for p in POLICIES)
        + f"{'EDF - FIFO':>18}",
    ]
    for coherence in TIMES:
        for background in BACKGROUND:
            for contract in CONTRACTS:
                rows = {
                    p: {
                        r[4]: r[5]
                        for r in sensitive
                        if r[0] == coherence
                        and r[1] == background
                        and r[2] == contract
                        and r[3] == p
                    }
                    for p in POLICIES
                }
                cells = "".join(f"{statistics.fmean(rows[p].values()):>16.3f}" for p in POLICIES)
                diff = [rows["edf"][s] - rows["fifo"][s] for s in range(seeds)]
                se = statistics.stdev(diff) / math.sqrt(seeds)
                note = f"{statistics.fmean(diff):+.3f} ± {se:.3f}"
                lines.append(f"  {coherence:>7g}{background:>12}{contract:>13}{cells}{note:>18}")
    text = "\n".join(lines) + "\n"
    write_atomic(OUT, text)
    print(text)


if __name__ == "__main__":
    main()
