"""Round by round: why does fidelity-first match the verifiers' solo score against a QKD background?

`position_mix.py` reports that under fidelity-first the two verifiers beside three QKD tenants score about what
they score alone (0.493 against 0.492) while finishing late (6.07 s against 1.52 s under EDF). The explanation in
the text is that fidelity-first serves the QKD tenants first, because their fidelity bar is higher, so a verifier
loses the one round it has outstanding while it is starved, and then runs the remaining rounds alone once the
background has gone. That is a claim about individual rounds, so this script reads them off the traces.

For each policy, over the same seeds, every verifier round is placed in a phase by when its request was issued:
before the background tenants finish, or after. A round counts as starved if it waited longer than 100 times its
response bound. The solo baseline is the same two verifiers with no background tenants.

    python scripts/paper/verifier_rounds.py

Writes `data/verifier_rounds.txt` (summary over seeds) and `data/verifier_rounds_seed0.csv` (every round of one seed).
"""

from __future__ import annotations

import csv
import multiprocessing
import statistics
from pathlib import Path

from qnetbench.characterize.provenance import write_atomic
from qnetbench.tenancy import ExecutionModel, TenantSpec, application_utility, run_tenants
from qnetbench.topology import LinkModel
from qnetbench.trace.events import ContractViolation, EntanglementDelivered, EntanglementRequested

OUT = Path(__file__).parent / "data" / "verifier_rounds.txt"
CSV = Path(__file__).parent / "data" / "verifier_rounds_seed0.csv"
POLICIES = ("fifo", "fidelity_first", "edf")
SEEDS = 64
RATE = 160.0
ROUNDS = 96
BOUND = 1e-2  # the verifier's response budget, seconds
STARVED = 100 * BOUND


def _run(args):
    policy, background, seed = args
    tenants = [TenantSpec(f"pv{i}", "position_verification", {"rounds": ROUNDS}) for i in range(2)]
    if background:
        tenants += [TenantSpec(f"bg{i}", "qkd", {"rounds": 256}) for i in range(3)]
    run = run_tenants(
        tenants,
        seed=seed,
        arbitration=f"policy:{policy}",
        link=LinkModel(1.0 / RATE, 0.99, 0.0),
        classical_latency=1e-3,
        model=ExecutionModel(arrivals="closed_loop"),
    )
    background_end = max((run.traces[f"bg{i}"][-1].t for i in range(3)), default=0.0) if background else 0.0
    rounds = []
    for tenant in ("pv0", "pv1"):
        trace = run.traces[tenant]
        requested = {e.req_id: e.t for e in trace if isinstance(e, EntanglementRequested)}
        delivered = {e.req_id: e for e in trace if isinstance(e, EntanglementDelivered)}
        late = {e.req_id for e in trace if isinstance(e, ContractViolation)}
        for index, (req_id, t_request) in enumerate(sorted(requested.items(), key=lambda item: item[1])):
            latency = delivered[req_id].latency
            rounds.append(
                {
                    "tenant": tenant,
                    "round": index,
                    "requested_t": t_request,
                    "delivered_t": t_request + latency,
                    "latency": latency,
                    "late": req_id in late,
                    "phase": "background" if t_request < background_end else "after",
                    "starved": latency > STARVED,
                }
            )
    return {
        "policy": policy,
        "background": background,
        "seed": seed,
        "utility": statistics.fmean(application_utility(run.traces[t]) for t in ("pv0", "pv1")),
        "finish": max(run.traces[t][-1].t for t in ("pv0", "pv1")),
        "background_end": background_end,
        "rounds": rounds,
    }


def _summarise(results: list[dict]) -> dict[str, float]:
    def per_seed(phase: str | None, key: str) -> list[float]:
        values = []
        for r in results:
            chosen = [x for x in r["rounds"] if phase is None or x["phase"] == phase]
            values.append(sum(x[key] for x in chosen) if key != "n" else len(chosen))
        return values

    def mean(values: list[float]) -> float:
        return statistics.fmean(values)

    after_rounds = per_seed("after", "n")
    after_late = per_seed("after", "late")
    ok_after = sum(n - late for n, late in zip(after_rounds, after_late, strict=True))
    return {
        "utility": mean([r["utility"] for r in results]),
        "finish": mean([r["finish"] for r in results]),
        "background_end": mean([r["background_end"] for r in results]),
        "rounds_in_background": mean(per_seed("background", "n")),
        "late_in_background": mean(per_seed("background", "late")),
        "starved": mean(per_seed(None, "starved")),
        "rounds_after": mean(after_rounds),
        "late_after": mean(after_late),
        "verified_after_rate": ok_after / sum(after_rounds) if sum(after_rounds) else float("nan"),
        "longest_wait": mean([max(x["latency"] for x in r["rounds"]) for r in results]),
    }


def main() -> None:
    jobs = [(p, True, s) for p in POLICIES for s in range(SEEDS)] + [("fifo", False, s) for s in range(SEEDS)]
    with multiprocessing.Pool() as pool:
        results = pool.map(_run, jobs)
    solo = [r for r in results if not r["background"]]
    solo_rate = statistics.fmean(1 - sum(x["late"] for x in r["rounds"]) / len(r["rounds"]) for r in solo)

    header = (
        f"Two position_verification tenants ({ROUNDS} rounds, {BOUND * 1e3:g} ms bound) beside three qkd tenants, "
        f"{RATE:g} pairs/s, {SEEDS} seeds, closed loop.\n"
        "A round is 'in background' if requested before the last qkd tenant finished. Starved: waited more than "
        f"{STARVED:g} s.\n"
        "Per-seed means. 'late' counts rounds whose pair missed the bound, which is what makes a round fail.\n"
        f"Solo baseline (no background, any policy): {solo_rate:.3f} of rounds verified, finish "
        f"{statistics.fmean(r['finish'] for r in solo):.2f} s.\n"
    )
    columns = (
        f"{'policy':<16}{'utility':>8}{'finish':>8}{'bg ends':>9}{'rounds in bg':>14}{'late in bg':>12}"
        f"{'starved':>9}{'longest wait':>14}{'rounds after':>14}{'late after':>12}{'verified after':>16}"
    )
    lines = [header, columns]
    for policy in POLICIES:
        s = _summarise([r for r in results if r["background"] and r["policy"] == policy])
        lines.append(
            f"{policy:<16}{s['utility']:>8.3f}{s['finish']:>8.2f}{s['background_end']:>9.2f}"
            f"{s['rounds_in_background']:>14.1f}{s['late_in_background']:>12.1f}{s['starved']:>9.2f}"
            f"{s['longest_wait']:>14.2f}{s['rounds_after']:>14.1f}{s['late_after']:>12.1f}"
            f"{s['verified_after_rate']:>16.3f}"
        )
    write_atomic(OUT, "\n".join(lines) + "\n")

    CSV.parent.mkdir(parents=True, exist_ok=True)
    with CSV.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["policy", "background", "tenant", "round", "requested_t", "delivered_t", "latency", "late", "phase", "starved"]
        )
        for r in results:
            if r["seed"] != 0:
                continue
            for x in r["rounds"]:
                writer.writerow(
                    [r["policy"], int(r["background"]), x["tenant"], x["round"], f"{x['requested_t']:.6f}",
                     f"{x['delivered_t']:.6f}", f"{x['latency']:.6f}", int(x["late"]), x["phase"], int(x["starved"])]
                )
    print("\n".join(lines))


if __name__ == "__main__":
    main()
