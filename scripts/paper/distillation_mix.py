#!/usr/bin/env python3
"""The distillation-heavy mix behind the negative result (Sec. VIII-D).

A distillation tenant is the one workload in the suite whose utility scales with
the *number* of pairs it receives rather than the quality of each, so it ought to
be the mix on which a fidelity-ordered policy does badly. It is not, and the
reason is a limitation of the contention model rather than a fact about
distillation: the model scores each request as a binary contract outcome, and a
tenant that declares a low `min_fidelity` and no deadline has its contract met
the moment it is served at all, however long it waited.

This is the only cell of Section VIII that was once reported from a single draw
of the superseded synchronised model. It is replicated here on the same footing
as every other cell -- independent arrival draws, 100 requests per tenant, the
Table IV operating point -- so that R3 and R7 hold for it too.

    python scripts/paper/distillation_mix.py > scripts/paper/data/distillation_mix.txt
"""

from __future__ import annotations

import random
import statistics as st
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _sweep_common import label  # noqa: E402

from qnetbench.contention import (  # noqa: E402
    CAPACITY,
    COHERENCE_TIME,
    DRAWS,
    LINK_FIDELITY,
    N_REQUESTS,
    Tenant,
    app_profile,
    ranking_experiment,
    winning_policies,
)

INTERVAL = 0.03
POLICIES = ("fifo", "fidelity_first", "edf")


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


def main() -> None:
    scores: dict[str, list[float]] = {p: [] for p in POLICIES}
    wins: Counter[str] = Counter()
    # Against the fidelity-heavy mix, which is the column the expected third one
    # was meant to differ from.
    inversions = 0

    for seed in range(DRAWS):
        rng = random.Random(seed)
        mixes = {
            "distillation_heavy": group("distillation", 4, rng) + group("qkd", 1, rng),
            "fidelity_heavy": group("bqc", 2, rng)
            + group("chsh", 2, rng)
            + group("qkd", 1, rng),
        }
        exp = ranking_experiment(
            mixes,
            capacity=CAPACITY,
            link_fidelity=LINK_FIDELITY,
            coherence_time=COHERENCE_TIME,
        )
        for p in POLICIES:
            scores[p].append(exp["distillation_heavy"][p].aggregate_utility)
        dist_w = winning_policies(exp["distillation_heavy"])
        wins[label(dist_w)] += 1
        if not (dist_w & winning_policies(exp["fidelity_heavy"])):
            inversions += 1

    print(
        f"distillation-heavy mix (4 distillation + 1 qkd) at capacity "
        f"{CAPACITY:.0f} pairs/s: {DRAWS} independent arrival draws, "
        f"{N_REQUESTS} requests/tenant."
    )
    print("winner = every policy tied for the top score.\n")
    print("   contract satisfaction, mean +- sd across draws")
    for p in POLICIES:
        print(f"      {p:15s} {st.mean(scores[p]):.3f} +- {st.stdev(scores[p]):.3f}")
    print()
    print("   winning set over the draws:")
    for name, n in wins.most_common():
        print(f"      {name:15s} {n:>3}/{DRAWS}")
    print()
    print(
        f"   draws with no policy in common with the fidelity-heavy mix: "
        f"{inversions}/{DRAWS}"
    )


if __name__ == "__main__":
    main()
