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

import statistics as st

from qnetbench.contention import (
    COHERENCE_TIME,
    DRAWS,
    LINK_FIDELITY,
    N_REQUESTS,
    burstiness_mixes,
    ranking_experiment,
)


def main() -> None:
    # One independent tenant population per draw, reused across capacities.
    populations = [burstiness_mixes(n_requests=N_REQUESTS, seed=seed) for seed in range(DRAWS)]
    print(
        f"burstiness at fixed load: {DRAWS} independent arrival draws, "
        f"{N_REQUESTS} requests/tenant. Rates are FIFO, mean +- sd across draws."
    )
    print()
    hdr = f"{'capacity':>8}{'bursty':>16}{'smooth':>16}{'cost':>8}"
    print(hdr)
    print("-" * len(hdr))
    for cap in list(range(40, 221, 20)):
        bursty, smooth = [], []
        for mixes in populations:
            exp = ranking_experiment(
                mixes,
                capacity=cap,
                link_fidelity=LINK_FIDELITY,
                coherence_time=COHERENCE_TIME,
            )
            bursty.append(exp["bursty"]["fifo"].aggregate_utility)
            smooth.append(exp["smooth"]["fifo"].aggregate_utility)
        bm, sm = st.mean(bursty), st.mean(smooth)
        print(
            f"{cap:>8}{f'{bm:.3f} +- {st.stdev(bursty):.3f}':>16}"
            f"{f'{sm:.3f} +- {st.stdev(smooth):.3f}':>16}{sm - bm:>8.3f}"
        )


if __name__ == "__main__":
    main()
