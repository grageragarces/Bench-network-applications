"""The teleported CNOT, in both input bases."""

from __future__ import annotations

import math
import statistics

import pytest

from qnetbench.backends.reference.engine import ApplicationFailure
from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.tenancy import TenantSpec, application_utility, run_tenants
from qnetbench.topology import LinkModel, line2

PERFECT = line2(link=LinkModel(link_fidelity=1.0, fidelity_std=0.0))


@pytest.mark.parametrize("basis", ["z", "x"])
@pytest.mark.parametrize("seed", range(4))
def test_gate_is_exact_noiseless(basis: str, seed: int) -> None:
    events = run_once(
        "distributed_gate", seed=seed, topology=PERFECT, cfg={"basis": basis, "reps": 16}
    )
    assert compute_report(events).app_utility == 1.0


def test_default_basis_is_z() -> None:
    assert run_once("distributed_gate", seed=3) == run_once(
        "distributed_gate", seed=3, cfg={"basis": "z"}
    )


def test_unknown_basis_is_an_error() -> None:
    with pytest.raises(ApplicationFailure, match="basis must be one of"):
        run_once("distributed_gate", seed=0, cfg={"basis": "y"})


def _shared_utility(basis: str, coherence: float) -> float:
    """Three gate tenants sharing one link, so data qubits wait in memory for their pairs."""
    values = []
    for seed in range(4):
        run = run_tenants(
            [
                TenantSpec(f"g{i}", "distributed_gate", {"basis": basis, "reps": 16})
                for i in range(3)
            ],
            seed=seed,
            arbitration="policy:fifo",
            link=LinkModel(1 / 160, 1.0, 0.0),
            classical_latency=1e-3,
            coherence_time=coherence,
        )
        values.append(statistics.fmean(application_utility(t) for t in run.traces.values()))
    return statistics.fmean(values)


def test_dephasing_reaches_only_the_x_basis() -> None:
    # Computational basis states are untouched by dephasing; |+/-> states are not.
    assert _shared_utility("z", 0.01) == _shared_utility("z", math.inf) == 1.0
    assert _shared_utility("x", math.inf) == 1.0
    assert _shared_utility("x", 0.01) < 0.6
