"""Shared helpers for the ranking-inversion sensitivity sweeps.

All three sweeps replicate over independent arrival draws rather than reporting
a single realisation, and all three report ties explicitly: at several operating
points two or three policies score exactly the same, and resolving that by
argmax invents a winner. A "winner" here is therefore a set.
"""

from __future__ import annotations

from collections import Counter

from qnetbench.contention import (
    COHERENCE_TIME,
    DRAWS,
    LINK_FIDELITY,
    N_REQUESTS,
    Tenant,
    default_mixes,
    ranking_experiment,
    winning_policies,
)

MIXES = ("deadline_heavy", "fidelity_heavy")
SHORT = {"fifo": "fifo", "fidelity_first": "ff", "edf": "edf"}


def draws(n: int = DRAWS, n_requests: int = N_REQUESTS) -> list[dict[str, list[Tenant]]]:
    """One independent tenant population per draw, built once and reused across
    every point of a sweep so the sweep varies only its own axis."""
    return [default_mixes(n_requests, seed=seed) for seed in range(n)]


def label(policies: frozenset[str]) -> str:
    return "/".join(SHORT[p] for p in sorted(policies))


def point(
    populations: list[dict[str, list[Tenant]]],
    *,
    capacity: float = 0.0,
    coherence_time: float = COHERENCE_TIME,
) -> tuple[dict[str, tuple[str, int]], int, dict[str, float]]:
    """Evaluate one sweep point over every draw.

    Returns the modal winner and its support per mix, the number of draws on
    which the two mixes disagreed, and the mean satisfaction of the best policy.
    """
    wins: dict[str, Counter[str]] = {m: Counter() for m in MIXES}
    rate: dict[str, float] = dict.fromkeys(MIXES, 0.0)
    inversions = 0
    for mixes in populations:
        exp = ranking_experiment(
            mixes,
            capacity=capacity,
            link_fidelity=LINK_FIDELITY,
            coherence_time=coherence_time,
        )
        best = {}
        for mix in MIXES:
            w = winning_policies(exp[mix])
            best[mix] = w
            wins[mix][label(w)] += 1
            rate[mix] += max(r.aggregate_utility for r in exp[mix].values())
        if not (best["deadline_heavy"] & best["fidelity_heavy"]):
            inversions += 1
    n = len(populations)
    modal = {m: wins[m].most_common(1)[0] for m in MIXES}
    return modal, inversions, {m: rate[m] / n for m in MIXES}
