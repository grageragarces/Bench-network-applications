"""What rate and burst shape does the SeQUeNCe supply produce, and what controls them?

The adapter runs at memo_size=50 over 1 km with attenuation 0. Mapping one link specification
onto all three supplies needs to know how rate responds to its settings.

    .venv/bin/python scripts/paper/sequence_rate.py
"""

from __future__ import annotations

import statistics

from qnetbench.backends.sequence.supply import generate_supply


def describe(memo_size: int, distance_m: float, attenuation: float, seed: int = 1) -> str:
    supply = generate_supply(
        seed=seed,
        window_s=1.0,
        link_fidelity=0.99,
        classical_latency_s=1e-3,
        target_fidelity=0.5,
        distance_m=distance_m,
        attenuation=attenuation,
        memo_size=memo_size,
    )
    gaps = supply.inter_arrivals[1:]
    if len(gaps) < 2:
        return f"{len(supply):>7} pairs"
    mean, median = statistics.fmean(gaps), statistics.median(gaps)
    ratio = mean / median if median > 0 else float("inf")
    cv = statistics.stdev(gaps) / mean if mean > 0 else 0.0
    return (
        f"{len(supply):>7} pairs/s  mean gap {mean * 1e3:>8.3f} ms  median {median * 1e3:>8.3f} ms  "
        f"mean/median {ratio:>7.1f}  cv {cv:>6.2f}  F {statistics.fmean(supply.fidelities):.4f}"
    )


print("memo_size, 1 km, attenuation 0")
for memo in (1, 2, 5, 10, 50):
    print(f"  memo {memo:>3}  {describe(memo, 1000.0, 0.0)}")
print("distance, memo_size 1, attenuation 0")
for distance in (1000.0, 5000.0, 10000.0, 20000.0, 50000.0, 100000.0):
    print(f"  {distance / 1000:>5.0f} km  {describe(1, distance, 0.0)}")
print("distance, memo_size 1, attenuation 0.2 dB/km")
for distance in (1000.0, 10000.0, 20000.0, 50000.0):
    print(f"  {distance / 1000:>5.0f} km  {describe(1, distance, 0.0002)}")
