"""Per-application demand-signature report: the single-trace signature plus the
summarised fidelity/staleness curves, and a cross-application table. This is the
machine-readable form of the characterization (Deliverable 2)."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from qnetbench.characterize.curves import CharacterizationCurves, characterize_curves
from qnetbench.characterize.signature import TraceSignature, characterize_trace
from qnetbench.harness.runner import run_once


class AppSignature(BaseModel):
    """The full demand signature for one application."""

    app: str
    trace: TraceSignature
    fidelity_threshold: float | None = None  # delivered fidelity at which utility ≥ 0.5
    staleness_halflife: float | None = None  # pair age (s) at which utility halves


def characterize_app(
    app: str,
    *,
    coherence_time: float = 1e-3,
    seeds: Sequence[int] = range(8),
) -> tuple[AppSignature, CharacterizationCurves]:
    """Characterize one application: returns its signature and the raw curves."""
    trace = characterize_trace(run_once(app, seed=0))
    curves = characterize_curves(app, coherence_time=coherence_time, seeds=seeds)
    signature = AppSignature(
        app=app,
        trace=trace,
        fidelity_threshold=curves.fidelity_threshold,
        staleness_halflife=curves.staleness_halflife,
    )
    return signature, curves


def _fmt(value: float | None, spec: str) -> str:
    return format(value, spec) if value is not None else "—"


def render_table(signatures: list[AppSignature]) -> str:
    """A compact cross-application demand-signature table."""
    header = (
        f"{'app':24} {'parties':>7} {'cv':>6} {'fano':>6} {'msg/pair':>9} "
        f"{'deadline':>8} {'F½util':>7} {'stale½(ms)':>11}"
    )
    lines = [header, "-" * len(header)]
    for s in signatures:
        t = s.trace
        half_ms = s.staleness_halflife * 1e3 if s.staleness_halflife is not None else None
        lines.append(
            f"{s.app:24} {t.n_parties:>7} {t.request_cv:>6.2f} {t.fano_factor:>6.2f} "
            f"{t.msgs_per_pair:>9.2f} {t.deadline_fraction:>8.2f} "
            f"{_fmt(s.fidelity_threshold, '.3f'):>7} {_fmt(half_ms, '.2f'):>11}"
        )
    return "\n".join(lines)
