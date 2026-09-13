"""Per-application demand-signature report: the single-trace signature plus the
summarised fidelity/staleness curves, and a cross-application table. This is the
machine-readable form of the characterization (Deliverable 2)."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from qnetbench.characterize.curves import SEEDS, CharacterizationCurves, characterize_curves
from qnetbench.characterize.signature import TraceSignature, characterize_trace
from qnetbench.harness.runner import run_once


class AppSignature(BaseModel):
    """The full demand signature for one application."""

    app: str
    trace: TraceSignature
    fidelity_threshold: float | None = None  # delivered fidelity at mid-range utility
    # u(F=1.0) - u(F=0.5): how much utility the application gains across the swept
    # fidelity range. A near-zero range is what "fidelity-insensitive" actually
    # means; the threshold alone cannot say it.
    fidelity_range: float | None = None
    staleness_halflife: float | None = None  # pair age (s) at which utility halves
    # Same crossing measured from the curve's asymptotic floor; see
    # curves.CharacterizationCurves.staleness_halflife_range. Reported alongside,
    # not instead: a large gap between the two means the absolute half-life is set
    # by a nearly flat tail grazing the level, and is poorly resolved.
    staleness_halflife_range: float | None = None
    # Std across seeds of the crossing point itself (see curves._crossing_spread),
    # not of the utility values that produced it.
    fidelity_threshold_std: float | None = None
    staleness_halflife_std: float | None = None
    # Width of the interval the crossing was finally bracketed in, after bisection
    # refinement — the resolution of the reported crossing, distinct from and often
    # larger than the seed spread above.
    fidelity_threshold_bracket: float | None = None
    staleness_halflife_bracket: float | None = None


def characterize_app(
    app: str,
    *,
    coherence_time: float = 1e-3,
    seeds: Sequence[int] = range(SEEDS),
) -> tuple[AppSignature, CharacterizationCurves]:
    """Characterize one application: returns its signature and the raw curves."""
    trace = characterize_trace(run_once(app, seed=0))
    curves = characterize_curves(app, coherence_time=coherence_time, seeds=seeds)
    signature = AppSignature(
        app=app,
        trace=trace,
        fidelity_threshold=curves.fidelity_threshold,
        fidelity_range=curves.fidelity_range,
        staleness_halflife=curves.staleness_halflife,
        staleness_halflife_range=curves.staleness_halflife_range,
        fidelity_threshold_std=curves.fidelity_threshold_std,
        staleness_halflife_std=curves.staleness_halflife_std,
        fidelity_threshold_bracket=curves.fidelity_threshold_bracket,
        staleness_halflife_bracket=curves.staleness_halflife_bracket,
    )
    return signature, curves


def _fmt(value: float | None, spec: str) -> str:
    return format(value, spec) if value is not None else "—"


def _fmt_pm(value: float | None, std: float | None, spec: str) -> str:
    if value is None:
        return "—"
    if not std:
        return format(value, spec)
    return f"{format(value, spec)}±{format(std, spec)}"


def render_table(signatures: list[AppSignature]) -> str:
    """A compact cross-application demand-signature table."""
    header = (
        f"{'app':24} {'parties':>7} {'cv':>6} {'fano':>6} {'msg/pair':>9} "
        f"{'deadline':>8} {'F½util (±std)':>15} {'ΔF':>6} {'stale½(ms, ±std)':>18} "
        f"{'stale½r(ms)':>11}"
    )
    lines = [header, "-" * len(header)]
    for s in signatures:
        t = s.trace
        half_ms = s.staleness_halflife * 1e3 if s.staleness_halflife is not None else None
        half_ms_r = (
            s.staleness_halflife_range * 1e3 if s.staleness_halflife_range is not None else None
        )
        half_ms_std = (
            s.staleness_halflife_std * 1e3 if s.staleness_halflife_std is not None else None
        )
        lines.append(
            f"{s.app:24} {t.n_parties:>7} {t.request_cv:>6.2f} {t.fano_factor:>6.2f} "
            f"{t.msgs_per_pair:>9.2f} {t.deadline_fraction:>8.2f} "
            f"{_fmt_pm(s.fidelity_threshold, s.fidelity_threshold_std, '.3f'):>15} "
            f"{_fmt(s.fidelity_range, '.2f'):>6} "
            f"{_fmt_pm(half_ms, half_ms_std, '.3f'):>18} "
            f"{_fmt(half_ms_r, '.3f'):>11}"
        )
    return "\n".join(lines)
