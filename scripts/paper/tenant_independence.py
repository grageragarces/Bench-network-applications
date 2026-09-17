#!/usr/bin/env python3
"""Tenant independence and replication for the ranking-inversion result.

The contention experiment reported in Sec. VIII builds each tenant with
`app_profile`, which reads an application's arrival pattern from a run at a fixed
seed. Tenants of the same application therefore shared a pattern, and every
tenant started at t=0, so a mix of "four distributed_gate tenants plus one qkd
tenant" was really two arrival streams, one of them four-fold synchronised.

This script quantifies what that cost and what the result looks like without it:

  A. the same mixes with synchronised vs independent tenants, at the original
     operating point and scale;
  B. the headline comparison replicated over 32 independent arrival draws at a
     scale where the resolution floor is 1/500 rather than 1/60;
  C. a capacity sweep under independent tenants, reporting ties explicitly
     rather than resolving them by argmax.

    python scripts/paper/tenant_independence.py > scripts/paper/data/tenant_independence.txt
"""

from __future__ import annotations

import statistics as st

from qnetbench.contention import (
    COHERENCE_TIME,
    LINK_FIDELITY,
    default_mixes,
    ranking_experiment,
)

POLICIES = ("fifo", "fidelity_first", "edf")
MIXES = ("deadline_heavy", "fidelity_heavy")
SEEDS = 32
N_REQUESTS = 100
CAPACITY = 160.0  # recalibrated: see section B


def _winners(mixes, capacity: float) -> dict[str, tuple[set[str], dict[str, float]]]:
    exp = ranking_experiment(
        mixes, capacity=capacity, link_fidelity=LINK_FIDELITY, coherence_time=COHERENCE_TIME
    )
    out = {}
    for mix, res in exp.items():
        scores = {p: res[p].aggregate_utility for p in POLICIES}
        top = max(scores.values())
        out[mix] = ({p for p in POLICIES if scores[p] == top}, scores)
    return out


def section_a() -> None:
    print("A. Synchronised vs independent tenants (12 requests/tenant, capacity 120)")
    print("   Synchronised is the original model: same arrival pattern, all from t=0.\n")
    print(f"   {'model':>14}  {'mix':>15}  {'fifo':>7} {'fid_1st':>7} {'edf':>7}  winner")
    models = (
        ("synchronised", default_mixes(12)),
        ("independent", default_mixes(12, seed=0)),
    )
    for label, mixes in models:
        for mix, (win, sc) in _winners(mixes, 120.0).items():
            print(
                f"   {label:>14}  {mix:>15}  {sc['fifo']:>7.3f} {sc['fidelity_first']:>7.3f} "
                f"{sc['edf']:>7.3f}  {'/'.join(sorted(win))}"
            )
    print()


def section_b() -> None:
    print(f"B. Replication: {SEEDS} independent arrival draws, {N_REQUESTS} requests/tenant,")
    print(f"   capacity {CAPACITY:.0f} pairs/s against {5/0.03:.0f} req/s aggregate demand.")
    print(f"   Resolution floor 1/{5*N_REQUESTS} = {1/(5*N_REQUESTS):.4f} (was 1/60 = 0.0167).\n")
    acc = {m: {p: [] for p in POLICIES} for m in MIXES}
    inversions = 0
    for seed in range(SEEDS):
        w = _winners(default_mixes(N_REQUESTS, seed=seed), CAPACITY)
        for mix, (_, sc) in w.items():
            for p in POLICIES:
                acc[mix][p].append(sc[p])
        if not (w["deadline_heavy"][0] & w["fidelity_heavy"][0]):
            inversions += 1
    for mix in MIXES:
        print(f"   {mix}")
        for p in POLICIES:
            v = acc[mix][p]
            print(f"      {p:15s} {st.mean(v):.3f} +- {st.stdev(v):.3f}")
        order = sorted(((st.mean(acc[mix][p]), p) for p in POLICIES), reverse=True)
        (m1, p1), (m2, p2) = order[0], order[1]
        se = (st.stdev(acc[mix][p1]) ** 2 / SEEDS + st.stdev(acc[mix][p2]) ** 2 / SEEDS) ** 0.5
        sigma = (m1 - m2) / se if se else float("inf")
        print(f"      -> {p1} over {p2}: +{m1 - m2:.3f} ({sigma:.1f} sigma)")
    print(f"   inversion on {inversions}/{SEEDS} draws\n")


def section_c() -> None:
    print("C. Capacity sweep under independent tenants (6 draws per point).")
    print("   'tie' counts draws whose winning score was shared by >1 policy.\n")
    print(
        f"   {'capacity':>8}  {'dh winner':>22} {'fh winner':>22}"
        f"  {'inv':>5}  {'dh':>6} {'fh':>6}"
    )
    for cap in (60, 80, 100, 120, 140, 160, 166, 175, 185, 200, 250, 320):
        dh_w: dict[str, int] = {}
        fh_w: dict[str, int] = {}
        ties = 0
        inv = 0
        rates = {m: [] for m in MIXES}
        draws = 6
        for seed in range(draws):
            w = _winners(default_mixes(N_REQUESTS, seed=seed), float(cap))
            for mix, (win, sc) in w.items():
                key = "/".join(sorted(win))
                (dh_w if mix == "deadline_heavy" else fh_w)[key] = (
                    (dh_w if mix == "deadline_heavy" else fh_w).get(key, 0) + 1
                )
                rates[mix].append(max(sc.values()))
                ties += len(win) > 1
            if not (w["deadline_heavy"][0] & w["fidelity_heavy"][0]):
                inv += 1
        top_dh = max(dh_w, key=lambda k: dh_w[k])
        top_fh = max(fh_w, key=lambda k: fh_w[k])
        print(
            f"   {cap:>8}  {top_dh + f' ({dh_w[top_dh]}/{draws})':>22} "
            f"{top_fh + f' ({fh_w[top_fh]}/{draws})':>22}  {inv}/{draws}  "
            f"{st.mean(rates['deadline_heavy']):>6.3f} {st.mean(rates['fidelity_heavy']):>6.3f}"
        )


if __name__ == "__main__":
    section_a()
    section_b()
    section_c()
