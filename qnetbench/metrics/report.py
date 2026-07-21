"""Standard metrics, computed only from a trace. Any third-party tool can produce
the same numbers from the JSONL without importing this module; we are just the
first consumer."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
from pydantic import BaseModel, Field

from qnetbench.trace.events import (
    AppOutcomeEvent,
    ClassicalMessage,
    ContractViolation,
    EntanglementDelivered,
    EntanglementRequested,
    Event,
    RunHeader,
)


class RoleResult(BaseModel):
    role: str
    node: str
    success: bool
    utility: float


class Report(BaseModel):
    # provenance
    app: str = ""
    backend: str = ""
    arbitration: str = ""
    topology: str = ""
    seed: int = 0
    sim_duration: float = 0.0

    # entanglement supply
    n_requests: int = 0
    n_delivered: int = 0
    delivered_rate: float = 0.0  # pairs / sim second
    mean_fidelity: float = 0.0
    fidelity_throughput: float = 0.0  # fidelity-weighted pairs / sim second

    # contracts
    violations: dict[str, int] = Field(default_factory=dict)
    violation_rate: float = 0.0  # violations / delivered

    # latency (request → delivery), seconds
    latency_mean: float = 0.0
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    latency_p99: float = 0.0

    # classical-communication coupling
    classical_msgs: int = 0
    classical_bytes: int = 0
    bytes_per_pair: float = 0.0
    msgs_per_pair: float = 0.0

    # application outcome
    app_success: bool = False
    app_utility: float = 0.0
    roles: list[RoleResult] = Field(default_factory=list)


def _percentile(values: list[float], q: float) -> float:
    return float(np.percentile(values, q)) if values else 0.0


def compute_report(events: Iterable[Event]) -> Report:
    events = list(events)
    report = Report()

    fidelities: list[float] = []
    latencies: list[float] = []
    times: list[float] = []
    roles: list[RoleResult] = []

    for ev in events:
        times.append(ev.t)
        if isinstance(ev, RunHeader):
            report.app = ev.app
            report.backend = ev.backend
            report.arbitration = ev.arbitration
            report.topology = ev.topology
            report.seed = ev.seed
        elif isinstance(ev, EntanglementRequested):
            report.n_requests += 1
        elif isinstance(ev, EntanglementDelivered):
            report.n_delivered += 1
            fidelities.append(ev.actual_fidelity)
            latencies.append(ev.latency)
        elif isinstance(ev, ContractViolation):
            report.violations[ev.violation] = report.violations.get(ev.violation, 0) + 1
        elif isinstance(ev, ClassicalMessage):
            report.classical_msgs += 1
            report.classical_bytes += ev.n_bytes
        elif isinstance(ev, AppOutcomeEvent):
            roles.append(
                RoleResult(role=ev.role, node=ev.node, success=ev.success, utility=ev.utility)
            )

    duration = (max(times) - min(times)) if times else 0.0
    report.sim_duration = duration

    report.mean_fidelity = float(np.mean(fidelities)) if fidelities else 0.0
    if duration > 0:
        report.delivered_rate = report.n_delivered / duration
        report.fidelity_throughput = float(np.sum(fidelities)) / duration

    total_violations = sum(report.violations.values())
    report.violation_rate = total_violations / report.n_delivered if report.n_delivered else 0.0

    report.latency_mean = float(np.mean(latencies)) if latencies else 0.0
    report.latency_p50 = _percentile(latencies, 50)
    report.latency_p95 = _percentile(latencies, 95)
    report.latency_p99 = _percentile(latencies, 99)

    if report.n_delivered:
        report.bytes_per_pair = report.classical_bytes / report.n_delivered
        report.msgs_per_pair = report.classical_msgs / report.n_delivered

    report.roles = roles
    report.app_success = bool(roles) and all(r.success for r in roles)
    report.app_utility = float(np.mean([r.utility for r in roles])) if roles else 0.0
    return report


def render(report: Report) -> str:
    v = ", ".join(f"{k}={n}" for k, n in sorted(report.violations.items())) or "none"
    return "\n".join(
        [
            f"app={report.app}  backend={report.backend}  "
            f"arbitration={report.arbitration}  seed={report.seed}",
            f"  app_success={report.app_success}  app_utility={report.app_utility:.3f}",
            f"  pairs: requested={report.n_requests} delivered={report.n_delivered} "
            f"rate={report.delivered_rate:.1f}/s  mean_fidelity={report.mean_fidelity:.3f}",
            f"  fidelity_throughput={report.fidelity_throughput:.1f}/s  "
            f"violations: {v}  violation_rate={report.violation_rate:.3f}",
            f"  latency(s): mean={report.latency_mean:.4f} p50={report.latency_p50:.4f} "
            f"p95={report.latency_p95:.4f} p99={report.latency_p99:.4f}",
            f"  classical: msgs={report.classical_msgs} bytes={report.classical_bytes} "
            f"bytes/pair={report.bytes_per_pair:.1f} msgs/pair={report.msgs_per_pair:.2f}",
        ]
    )
