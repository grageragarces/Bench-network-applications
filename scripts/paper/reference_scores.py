"""Reference scores for the suite's scheduling scenarios.

Each scenario fixes its tenants, contracts, link and execution model, and names the application
it is built around. A policy is scored on contract satisfaction over all tenants, and on the
utility and finish time of that application. The scores of the built-in policies and of the four
published schedulers in `fidelity_age_policies.py` are the baselines a new policy is compared
with.

    deadline_heavy   four distributed_gate tenants and one qkd tenant, paced, 32 draws
    fidelity_heavy   two bqc, two chsh and one qkd tenant, paced, 32 draws
    verifiers        two position_verification tenants beside three qkd tenants
    gates            two distributed_gate tenants with |+/-> inputs beside three qkd tenants,
                     T2 = 50 ms
    switch           two verifiers, two qkd tenants and the |+/-> gates on a four-leaf star

All run on the default execution model at 160 pairs/s with link fidelity 0.99 and 1 ms classical
delay. The last three start together and use 64 seeds.

    python scripts/paper/reference_scores.py
"""

from __future__ import annotations

import math
import multiprocessing
import statistics
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from executed_contention import CLASSICAL_LATENCY, _specs  # noqa: E402
from fidelity_age_policies import register_all  # noqa: E402
from star_switch import PLACEMENT, TENANTS  # noqa: E402

from qnetbench.characterize.provenance import write_atomic  # noqa: E402
from qnetbench.contention import COHERENCE_TIME, DRAWS, N_REQUESTS, default_mixes  # noqa: E402
from qnetbench.tenancy import (  # noqa: E402
    ExecutionModel,
    TenantSpec,
    application_utility,
    contract_satisfaction,
    run_tenants,
)
from qnetbench.topology import LinkModel  # noqa: E402

OUT = Path(__file__).parent / "data" / "reference_scores.txt"
RATE = 160.0
SEEDS = 64
POLICIES = (
    "fifo",
    "fidelity_first",
    "edf",
    "tp_max",
    "fid_max",
    "fa_index_intended",
    "fa_thr",
)


@dataclass(frozen=True)
class Scenario:
    name: str
    focus: str  # the application the scenario is built around
    seeds: int
    build: Callable[[int], tuple[list[TenantSpec], dict[str, tuple[str, str]] | None]]
    coherence: float
    closed_loop: bool


def _mix(name: str) -> Callable[[int], tuple[list[TenantSpec], None]]:
    def build(seed: int) -> tuple[list[TenantSpec], None]:
        return _specs(default_mixes(N_REQUESTS, seed=seed)[name], open_loop=False), None

    return build


def _beside_qkd(app: str, cfg: dict[str, object]) -> Callable[[int], tuple[list[TenantSpec], None]]:
    def build(_seed: int) -> tuple[list[TenantSpec], None]:
        tenants = [TenantSpec(f"f{i}", app, cfg) for i in range(2)]
        tenants += [TenantSpec(f"bg{i}", "qkd", {"rounds": 256}) for i in range(3)]
        return tenants, None

    return build


def _switch(_seed: int) -> tuple[list[TenantSpec], dict[str, tuple[str, str]]]:
    return list(TENANTS), dict(PLACEMENT)


SCENARIOS = (
    Scenario(
        "deadline_heavy", "distributed_gate", DRAWS, _mix("deadline_heavy"), COHERENCE_TIME, False
    ),
    Scenario("fidelity_heavy", "bqc", DRAWS, _mix("fidelity_heavy"), COHERENCE_TIME, False),
    Scenario(
        "verifiers",
        "position_verification",
        SEEDS,
        _beside_qkd("position_verification", {"rounds": 96}),
        math.inf,
        True,
    ),
    Scenario(
        "gates",
        "distributed_gate",
        SEEDS,
        _beside_qkd("distributed_gate", {"reps": 64, "basis": "x"}),
        0.05,
        True,
    ),
    Scenario("switch", "position_verification", SEEDS, _switch, math.inf, True),
)
BY_NAME = {s.name: s for s in SCENARIOS}


def _setup() -> None:
    register_all(slot=1.0 / RATE)


def _cell(args: tuple[str, str, int]) -> tuple[tuple[str, str, int], tuple[float, float, float]]:
    scenario_name, policy, seed = args
    scenario = BY_NAME[scenario_name]
    tenants, placement = scenario.build(seed)
    run = run_tenants(
        tenants,
        seed=seed,
        arbitration=f"policy:{policy}",
        link=LinkModel(1.0 / RATE, 0.99, 0.0),
        classical_latency=CLASSICAL_LATENCY,
        coherence_time=scenario.coherence,
        model=ExecutionModel(arrivals="closed_loop") if scenario.closed_loop else ExecutionModel(),
        placement=placement,
    )
    focus = [t.name for t in tenants if t.app == scenario.focus]
    return args, (
        statistics.fmean(contract_satisfaction(run.traces[t.name]) for t in tenants),
        statistics.fmean(application_utility(run.traces[name]) for name in focus),
        max(run.traces[name][-1].t for name in focus),
    )


def main() -> None:
    work = [(s.name, p, seed) for s in SCENARIOS for p in POLICIES for seed in range(s.seeds)]
    with multiprocessing.Pool(initializer=_setup) as pool:
        results = dict(pool.map(_cell, work, chunksize=4))

    lines = [
        "Reference scores. Satisfaction is over all tenants. Utility and finish time (s) are those",
        "of the scenario's focus application. All are means over seeds.",
        "",
        f"{'scenario':16}{'focus':24}{'policy':20}{'satisfaction':>14}{'utility':>10}{'finish':>9}",
    ]
    for s in SCENARIOS:
        for p in POLICIES:
            rows = [results[(s.name, p, seed)] for seed in range(s.seeds)]
            sat, util, fin = (statistics.fmean(r[i] for r in rows) for i in range(3))
            lines.append(f"{s.name:16}{s.focus:24}{p:20}{sat:>14.3f}{util:>10.3f}{fin:>9.2f}")
        lines.append("")
    text = "\n".join(lines)
    write_atomic(OUT, text)
    print(text)


if __name__ == "__main__":
    main()
