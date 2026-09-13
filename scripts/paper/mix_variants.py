#!/usr/bin/env python3
"""Mix-composition sensitivity for the ranking-inversion result (Sec. VIII-C).

Companion to capacity_sweep.py and coherence_sweep.py: instead of sweeping a
continuous operating-point parameter, this perturbs the *composition* of the
two Table IV tenant mixes — swapping counts, and swapping which application
plays the role of the mix's minority tenant — at the Table IV capacity, link
fidelity, and coherence time, to check whether the inversion depends on the
exact five-tenant mixes chosen for Table IV.

    python scripts/paper/mix_variants.py > scripts/paper/data/mix_variants.txt
"""

from __future__ import annotations

from qnetbench.contention import (
    CAPACITY,
    COHERENCE_TIME,
    LINK_FIDELITY,
    app_profile,
    best_policy,
    ranking_experiment,
)


def group(app: str, count: int, n_requests: int = 12, interval: float = 0.03):
    return [app_profile(app, n_requests, interval) for _ in range(count)]


DEFAULT_DH = group("distributed_gate", 4) + group("qkd", 1)
DEFAULT_FH = group("bqc", 2) + group("chsh", 2) + group("qkd", 1)

VARIANTS = {
    "default (Table IV)": (DEFAULT_DH, DEFAULT_FH),
    "dh: 3 distributed_gate + 2 qkd": (group("distributed_gate", 3) + group("qkd", 2), DEFAULT_FH),
    "dh: 5 distributed_gate + 0 qkd (homogeneous)": (group("distributed_gate", 5), DEFAULT_FH),
    "dh: 2 distributed_gate + 3 dqc_ghz4": (group("distributed_gate", 2) + group("dqc_ghz4", 3), DEFAULT_FH),
    "dh: 4 distributed_gate + 1 multihop_qkd": (group("distributed_gate", 4) + group("multihop_qkd", 1), DEFAULT_FH),
    "fh: 3 bqc + 2 chsh (no qkd)": (DEFAULT_DH, group("bqc", 3) + group("chsh", 2)),
    "fh: 1 bqc + 3 chsh + 1 qkd": (DEFAULT_DH, group("bqc", 1) + group("chsh", 3) + group("qkd", 1)),
    "fh: 2 bqc + 2 verified_bqc + 1 qkd": (DEFAULT_DH, group("bqc", 2) + group("verified_bqc", 2) + group("qkd", 1)),
}


def main() -> None:
    header = f"{'variant':<45} {'dh_win':>15} {'fh_win':>15}  inversion"
    print(header)
    print("-" * len(header))
    for name, (dh_tenants, fh_tenants) in VARIANTS.items():
        mixes = {"deadline_heavy": dh_tenants, "fidelity_heavy": fh_tenants}
        exp = ranking_experiment(mixes, capacity=CAPACITY, link_fidelity=LINK_FIDELITY, coherence_time=COHERENCE_TIME)
        dh_win = best_policy(exp["deadline_heavy"])
        fh_win = best_policy(exp["fidelity_heavy"])
        print(f"{name:<45} {dh_win:>15} {fh_win:>15}  {dh_win != fh_win}")


if __name__ == "__main__":
    main()
