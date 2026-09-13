#!/usr/bin/env python3
"""Burstiness at fixed load (Sec. VIII).

Two mixes of the same application, same contracts, same tenant count and same mean
arrival rate; the only difference is whether each tenant replays its measured
inter-arrival pattern or issues on a perfectly regular cadence. This isolates the
burstiness axis of Section VI, which the earlier fixed-cadence arrival model could
not express at all.

    python scripts/paper/burstiness_sweep.py > scripts/paper/data/burstiness_sweep.txt
"""

from __future__ import annotations

from qnetbench.contention import (
    COHERENCE_TIME,
    LINK_FIDELITY,
    best_policy,
    burstiness_mixes,
    ranking_experiment,
)


def main() -> None:
    hdr = f"{'capacity':>8}{'bursty':>9}{'smooth':>9}{'cost':>8}   winners (bursty / smooth)"
    print(hdr)
    print("-" * len(hdr))
    for cap in list(range(20, 171, 10)):
        exp = ranking_experiment(
            burstiness_mixes(),
            capacity=cap,
            link_fidelity=LINK_FIDELITY,
            coherence_time=COHERENCE_TIME,
        )
        b, s = exp["bursty"], exp["smooth"]
        bu = b["fifo"].aggregate_utility
        su = s["fifo"].aggregate_utility
        print(
            f"{cap:>8}{bu:>9.3f}{su:>9.3f}{su - bu:>8.3f}   "
            f"{best_policy(b)} / {best_policy(s)}"
        )


if __name__ == "__main__":
    main()
