"""The three swap cells at F = 0.85 all lean low in `native_netsquid.py`, on shared seeds.

Fresh seeds, more of them, against the closed form (1 + p^2) / 2 with p = (4F - 1) / 3.

    python scripts/paper/swap_recheck.py
"""

from __future__ import annotations

import math
import multiprocessing
import statistics

from qnetbench.apps import get_app
from qnetbench.harness.runner import run_once
from qnetbench.tenancy import application_utility
from qnetbench.topology import LinkModel, default_topology


def _cell(args: tuple[float, int]) -> float:
    fidelity, seed = args
    roles = get_app("entanglement_swap").roles()
    topology = default_topology(roles, link=LinkModel(1e-3, fidelity, 0.0))
    return application_utility(
        run_once("entanglement_swap", seed=seed, topology=topology, cfg={"rounds": 256})
    )


def main() -> None:
    seeds = 512
    with multiprocessing.Pool() as pool:
        for fidelity in (0.85, 0.95):
            values = pool.map(_cell, [(fidelity, 5000 + s) for s in range(seeds)])
            mean = statistics.fmean(values)
            se = statistics.stdev(values) / math.sqrt(seeds)
            p = (4 * fidelity - 1) / 3
            expected = (1 + p * p) / 2
            print(
                f"swap F={fidelity:.2f}  predicted {expected:.4f}  measured {mean:.4f} ± {se:.4f}  "
                f"z {(mean - expected) / se:+.2f}  ({seeds} new seeds)"
            )


if __name__ == "__main__":
    main()
