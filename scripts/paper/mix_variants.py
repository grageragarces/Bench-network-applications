#!/usr/bin/env python3
"""Mix-composition robustness for the ranking-inversion result (Sec. VIII-C).

Mix composition is not a continuous knob, so instead of sweeping it we perturb
the Table IV mixes directly — changing tenant counts, and swapping which
application plays the minority role — and re-run each variant. Replicated over
independent arrival draws, with ties reported as ties.

    python scripts/paper/mix_variants.py > scripts/paper/data/mix_variants.txt
"""

from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _sweep_common import label  # noqa: E402

from qnetbench.contention import (  # noqa: E402
    CAPACITY,
    COHERENCE_TIME,
    LINK_FIDELITY,
    N_REQUESTS,
    Tenant,
    app_profile,
    ranking_experiment,
    winning_policies,
)

INTERVAL = 0.03
# Fewer draws than the capacity sweep: each variant rebuilds its tenants from
# scratch, and eight variants times 32 draws is a lot of application runs for a
# robustness check whose answer is already unanimous at eight.
VARIANT_DRAWS = 8


def group(app: str, count: int, rng: random.Random) -> list[Tenant]:
    """`count` tenants of one application, each with its own arrival draw."""
    return [
        app_profile(
            app,
            N_REQUESTS,
            INTERVAL,
            trace_seed=rng.randrange(1 << 30),
            phase=rng.uniform(0.0, INTERVAL),
        )
        for _ in range(count)
    ]


def variants(rng: random.Random) -> dict[str, tuple[list[Tenant], list[Tenant]]]:
    dh = group("distributed_gate", 4, rng) + group("qkd", 1, rng)
    fh = group("bqc", 2, rng) + group("chsh", 2, rng) + group("qkd", 1, rng)
    return {
        "default (Table IV)": (dh, fh),
        "dh: 3 distributed_gate + 2 qkd": (
            group("distributed_gate", 3, rng) + group("qkd", 2, rng), fh),
        "dh: 5 distributed_gate + 0 qkd (homogeneous)": (
            group("distributed_gate", 5, rng), fh),
        "dh: 2 distributed_gate + 3 dqc_ghz4": (
            group("distributed_gate", 2, rng) + group("dqc_ghz4", 3, rng), fh),
        "dh: 4 distributed_gate + 1 multihop_qkd": (
            group("distributed_gate", 4, rng) + group("multihop_qkd", 1, rng), fh),
        "fh: 3 bqc + 2 chsh (no qkd)": (
            dh, group("bqc", 3, rng) + group("chsh", 2, rng)),
        "fh: 1 bqc + 3 chsh + 1 qkd": (
            dh, group("bqc", 1, rng) + group("chsh", 3, rng) + group("qkd", 1, rng)),
        "fh: 2 bqc + 2 verified_bqc + 1 qkd": (
            dh, group("bqc", 2, rng) + group("verified_bqc", 2, rng) + group("qkd", 1, rng)),
    }


def main() -> None:
    tally: dict[str, tuple[Counter[str], Counter[str], int]] = {}
    for seed in range(VARIANT_DRAWS):
        for name, (dh_t, fh_t) in variants(random.Random(seed)).items():
            exp = ranking_experiment(
                {"deadline_heavy": dh_t, "fidelity_heavy": fh_t},
                capacity=CAPACITY,
                link_fidelity=LINK_FIDELITY,
                coherence_time=COHERENCE_TIME,
            )
            dh_w = winning_policies(exp["deadline_heavy"])
            fh_w = winning_policies(exp["fidelity_heavy"])
            dc, fc, inv = tally.get(name, (Counter(), Counter(), 0))
            dc[label(dh_w)] += 1
            fc[label(fh_w)] += 1
            tally[name] = (dc, fc, inv + (not (dh_w & fh_w)))

    print(
        f"mix-composition variants at capacity {CAPACITY:.0f} pairs/s: "
        f"{VARIANT_DRAWS} independent arrival draws, {N_REQUESTS} requests/tenant."
    )
    print("winner = every policy tied for the top score; support = draws agreeing.\n")
    header = f"{'variant':<45} {'dh winner':>12} {'sup':>5} {'fh winner':>12} {'sup':>5}  inversion"
    print(header)
    print("-" * len(header))
    for name, (dc, fc, inv) in tally.items():
        (dw, dn), (fw, fn) = dc.most_common(1)[0], fc.most_common(1)[0]
        print(
            f"{name:<45} {dw:>12} {dn:>3}/{VARIANT_DRAWS:<2} {fw:>12} {fn:>3}/{VARIANT_DRAWS:<2}"
            f"  {inv}/{VARIANT_DRAWS}"
        )
    print(f"\n{sum(1 for _,_,i in tally.values() if i == VARIANT_DRAWS)} of {len(tally)} "
          f"variants show the inversion on every draw.")


if __name__ == "__main__":
    main()
