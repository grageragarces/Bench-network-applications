"""NetSquid backend + cross-backend equivalence.

The same applications, written once, must satisfy the same outcome invariants
whether entanglement is supplied by the reference link model or by NetSquid.
Physics differs, so noisy comparisons are asserted as tolerances.

Skipped unless the optional `netsquid` extra is installed (NetSquid needs numpy<2,
so it lives in its own environment — see the README).
"""

from __future__ import annotations

import importlib.util

import pytest

from qnetbench.apps import available_apps
from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, line2, star
from qnetbench.trace.events import AppOutcomeEvent

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("netsquid") is None,
    reason="requires the optional 'netsquid' extra (numpy<2; see README)",
)

BACKEND = "netsquid"
PERFECT = line2(link=LinkModel(attempt_latency=1e-3, link_fidelity=1.0, fidelity_std=0.0))
_PL = LinkModel(attempt_latency=1e-3, link_fidelity=1.0, fidelity_std=0.0)
PERFECT_STAR = star("charlie", ["alice", "bob"], link=_PL)


def _report(app: str, seed: int = 0, topo=None):
    return compute_report(run_once(app, seed=seed, backend=BACKEND, topology=topo))


def test_contract_override_applies_on_this_backend() -> None:
    events = run_once("qkd", backend=BACKEND, demand_override={"min_fidelity": 0.5})
    contracts = {e.demand.min_fidelity for e in events if e.kind == "ent_requested"}
    assert contracts == {0.5}


def test_all_apps_run_on_backend() -> None:
    for app in available_apps():  # default topology per app
        rep = _report(app)
        assert rep.backend == BACKEND
        assert rep.n_delivered > 0 or rep.qubits_sent > 0  # bb84 transmits qubits, not pairs


def test_backend_is_deterministic_per_seed() -> None:
    a = run_once("distributed_gate", seed=2, backend=BACKEND)
    b = run_once("distributed_gate", seed=2, backend=BACKEND)
    assert [e.model_dump() for e in a] == [e.model_dump() for e in b]


def test_noiseless_invariants_are_exact() -> None:
    assert _report("bqc", topo=PERFECT).app_utility == 1.0
    assert _report("distributed_gate", topo=PERFECT).app_utility == 1.0
    assert _report("anonymous_transmission", topo=PERFECT_STAR).app_utility == 1.0
    assert _report("qkd", topo=PERFECT).app_success
    assert _report("chsh", topo=PERFECT).app_success  # S > 2
    assert _report("clock_sync", topo=PERFECT).app_utility > 0.9
    assert _report("dqc_ghz4", topo=PERFECT).app_utility == 1.0  # mirror circuit -> |0…0>


def test_distributed_gate_truth_table_matches_across_backends() -> None:
    ref = compute_report(run_once("distributed_gate", seed=0, topology=PERFECT))
    sim = _report("distributed_gate", topo=PERFECT)
    assert ref.app_utility == sim.app_utility == 1.0


def test_qkd_qber_agrees_across_backends() -> None:
    noisy = line2(link=LinkModel(attempt_latency=1e-3, link_fidelity=0.9, fidelity_std=0.0))

    def qber(backend: str) -> float:
        events = run_once("qkd", seed=0, backend=backend, topology=noisy)
        return max(
            float(e.payload["qber"])  # type: ignore[arg-type]
            for e in events
            if isinstance(e, AppOutcomeEvent)
        )

    theory = 2 * (1 - 0.9) / 3  # ≈ 0.0667
    assert abs(qber("reference") - theory) < 0.05
    assert abs(qber(BACKEND) - theory) < 0.05


def test_concurrent_execution_runs_on_the_netsquid_supply():
    from qnetbench.tenancy import TenantSpec, contract_satisfaction, run_tenants
    from qnetbench.topology import LinkModel
    from qnetbench.trace.events import EntanglementDelivered

    tenants = [TenantSpec("key", "qkd", {"rounds": 10}), TenantSpec("bell", "chsh", {"rounds": 10})]
    link = LinkModel(1.0 / 160, 0.99, 0.0)
    runs = [
        run_tenants(
            tenants,
            seed=1,
            arbitration="policy:edf",
            link=link,
            classical_latency=1e-3,
            supply="netsquid",
        )
        for _ in range(2)
    ]
    assert runs[0].traces == runs[1].traces
    assert runs[0].supply == "netsquid"
    for trace in runs[0].traces.values():
        assert sum(isinstance(e, EntanglementDelivered) for e in trace) == 10
        assert contract_satisfaction(trace) >= 0.0


def test_one_link_description_sets_the_rate_on_the_netsquid_supply():
    from qnetbench.tenancy import _supply_backend
    from qnetbench.topology import LinkModel

    link = LinkModel(1.0 / 160, 0.99, 0.0)
    supplier = _supply_backend("netsquid", link, 1e-3, seed=1, window_s=1.0, timing="fixed")
    supply = next(iter(supplier._cursors.values())).supply
    gaps = supply.inter_arrivals[1:]
    rate = len(gaps) / sum(gaps)
    assert rate == pytest.approx(160.0, rel=1e-3)
    assert supply.classical_latency == 1e-3
    assert all(f == pytest.approx(0.99, abs=1e-9) for f in supply.fidelities)


def test_a_netsquid_source_can_have_random_timing():
    from qnetbench.tenancy import _supply_backend
    from qnetbench.topology import LinkModel

    link = LinkModel(1.0 / 500, 0.99, 0.0)
    supplier = _supply_backend("netsquid", link, 1e-3, seed=1, window_s=2.0, timing="exponential")
    gaps = next(iter(supplier._cursors.values())).supply.inter_arrivals[1:]
    mean = sum(gaps) / len(gaps)
    spread = (sum((g - mean) ** 2 for g in gaps) / len(gaps)) ** 0.5
    assert 1 / mean == pytest.approx(500, rel=0.1)
    assert spread / mean == pytest.approx(1.0, abs=0.15)  # exponential, where fixed gives 0


def test_netsquid_timing_is_random_by_default():
    from qnetbench.tenancy import _supply_backend
    from qnetbench.topology import LinkModel

    link = LinkModel(1.0 / 500, 0.99, 0.0)
    supplier = _supply_backend("netsquid", link, 1e-3, seed=1, window_s=2.0)
    gaps = next(iter(supplier._cursors.values())).supply.inter_arrivals[1:]
    mean = sum(gaps) / len(gaps)
    spread = (sum((g - mean) ** 2 for g in gaps) / len(gaps)) ** 0.5
    assert spread / mean == pytest.approx(1.0, abs=0.15)


def test_netsquid_refuses_an_unknown_timing():
    from qnetbench.tenancy import _supply_backend
    from qnetbench.topology import LinkModel

    with pytest.raises(ValueError, match="timing"):
        _supply_backend("netsquid", LinkModel(1e-3, 0.99, 0.0), 1e-3, 1, 0.1, timing="poisson")


def test_netsquid_dephased_supply_reaches_the_engine_as_dephasing():
    import statistics

    from qnetbench.backends.netsquid.supply import generate_supply
    from qnetbench.harness.runner import run_once
    from qnetbench.topology import LinkModel, line2
    from qnetbench.trace.events import AppOutcomeEvent

    supply = generate_supply(
        seed=0, window_s=0.2, link_fidelity=0.85, classical_latency_s=1e-3, noise="dephasing"
    )
    assert all(f == pytest.approx(0.85, abs=1e-9) for f in supply.fidelities)
    topo = line2(link=LinkModel(1e-3, 0.85, 0.0, "dephasing"))
    qbers = []
    for seed in range(4):
        events = run_once("qkd", seed=seed, backend="netsquid", topology=topo, cfg={"rounds": 512})
        outcome = next(e for e in events if isinstance(e, AppOutcomeEvent))
        qbers.append(float(outcome.payload["qber"]))
    assert statistics.fmean(qbers) == pytest.approx(0.075, abs=0.02)
