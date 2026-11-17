"""A worked example, as code that runs: one small application, evaluated alone and under three schedulers.

    python scripts/paper/worked_example.py

Two tracks use the same application: evaluating the application, and evaluating a scheduler.
"""

from __future__ import annotations

from qnetbench.api import AppOutcome, Basis, Demand
from qnetbench.apps import register_app
from qnetbench.harness.runner import run_once
from qnetbench.metrics.report import compute_report
from qnetbench.policies import register_policy
from qnetbench.tenancy import TenantSpec, application_utility, contract_satisfaction, run_tenants
from qnetbench.topology import LinkModel, default_topology


class SharedBits:
    """Both nodes measure 64 pairs and compare. Utility is the fraction that agree."""

    name = "shared_bits"

    def roles(self):
        return ["alice", "bob"]

    def run(self, host, role, cfg):
        peer = "bob" if role == "alice" else "alice"
        epr, classical = host.epr_socket(peer), host.classical_socket(peer)
        contract = Demand(min_fidelity=0.92, latency_budget=0.02)
        bits = [epr.request(1, contract)[0].qubit.measure(Basis.Z) for _ in range(64)]
        classical.send(bytes(bits))
        agree = sum(a == b for a, b in zip(bits, classical.recv(), strict=True)) / 64
        return AppOutcome(role=role, success=agree > 0.9, utility=agree)


class TightestBudget:
    """A new scheduler: whichever request declared the shortest time to deadline goes first."""

    name = "tightest_budget"

    def order(self, pending, now):
        def key(p):
            return (p.effective_deadline() - p.request_time, p.request_time, p.req_id)

        return [p.req_id for p in sorted(pending, key=key)]


register_app(SharedBits())
register_policy(TightestBudget())

# --- track 1: evaluate an application ------------------------------------------------------
print("Track 1: one application, its utility against the fidelity the link delivers")
for fidelity in (0.99, 0.95, 0.90, 0.80):
    link = LinkModel(1e-3, fidelity, 0.0)
    scores = [
        compute_report(
            run_once("shared_bits", seed=s, topology=default_topology(["alice", "bob"], link=link))
        )
        for s in range(32)
    ]
    utility = sum(r.app_utility for r in scores) / len(scores)
    print(f"  F = {fidelity:.2f}: utility {utility:.3f}, predicted {(1 + 2 * fidelity) / 3:.3f}")
report = compute_report(run_once("shared_bits", seed=0))
print(
    f"  default link: {report.n_delivered} pairs, {report.delivered_rate:.0f} pairs/s, "
    f"latency p50 {report.latency_p50 * 1e3:.2f} ms, {report.msgs_per_pair:.3f} messages per pair"
)

# --- track 2: evaluate a scheduler ---------------------------------------------------------
print("Track 2: the same application sharing a link, under three schedulers")
tenants = [
    TenantSpec("bits-1", "shared_bits"),
    TenantSpec("bits-2", "shared_bits"),
    TenantSpec("key", "qkd", {"rounds": 64}),
]
for policy in ("fifo", "tightest_budget", "edf"):
    satisfied, utility = [], []
    for seed in range(32):
        run = run_tenants(
            tenants,
            seed=seed,
            arbitration=f"policy:{policy}",
            link=LinkModel(1 / 60, 0.99, 0.0),
            classical_latency=1e-3,
            coherence_time=0.25,
        )
        satisfied.append(contract_satisfaction(run.traces["bits-1"]))
        utility.append(application_utility(run.traces["bits-1"]))
    print(
        f"  {policy:15} shared_bits satisfaction {sum(satisfied) / 32:.3f}, "
        f"utility {sum(utility) / 32:.3f}"
    )
