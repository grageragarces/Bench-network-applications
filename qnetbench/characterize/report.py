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
    # Std across seeds of the crossing point itself (see curves._crossing_stats),
    # not of the utility values that produced it.
    fidelity_threshold_std: float | None = None
    staleness_halflife_std: float | None = None
    # Width of the interval the crossing was finally bracketed in, after bisection
    # refinement — the resolution of the reported crossing, distinct from and often
    # larger than the seed spread above.
    fidelity_threshold_bracket: float | None = None
    staleness_halflife_bracket: float | None = None
    # Median of the per-seed crossings and how many of `n_seeds` produced one.
    # Where the mean curve plateaus just above the crossing level the aggregate
    # crossing above is None while a minority of seeds still cross; these fields
    # report that case as "mostly plateaus, k of n seeds resolve a half-life near
    # m" instead of a bare dash with an orphaned standard deviation next to it.
    fidelity_threshold_seed_median: float | None = None
    staleness_halflife_seed_median: float | None = None
    fidelity_threshold_seed_count: int = 0
    staleness_halflife_seed_count: int = 0
    n_seeds: int = 0


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
        fidelity_threshold_seed_median=curves.fidelity_threshold_seed_median,
        staleness_halflife_seed_median=curves.staleness_halflife_seed_median,
        fidelity_threshold_seed_count=curves.fidelity_threshold_seed_count,
        staleness_halflife_seed_count=curves.staleness_halflife_seed_count,
        n_seeds=curves.n_seeds,
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


def _half_life_ms(s: AppSignature) -> tuple[float | None, float | None, str]:
    """The staleness half-life cell: the aggregate crossing where there is one,
    otherwise the per-seed median, flagged, with the count of seeds behind it.

    Returning the median rather than a dash matters because the two disagree in a
    specific and reportable way: for an application whose staleness curve plateaus
    just above half its fresh-pair value, the mean curve never crosses while a
    minority of seeds do. A dash says "no data"; this says "mostly plateaus, k of n
    seeds still fall through, and they do so around here"."""
    if s.staleness_halflife is not None:
        std = s.staleness_halflife_std
        return (
            s.staleness_halflife * 1e3,
            std * 1e3 if std is not None else None,
            "",
        )
    if s.staleness_halflife_seed_median is not None and s.staleness_halflife_seed_count:
        return (
            s.staleness_halflife_seed_median * 1e3,
            None,
            f" ({s.staleness_halflife_seed_count}/{s.n_seeds})",
        )
    return (None, None, "")


def render_table(signatures: list[AppSignature]) -> str:
    """A compact cross-application demand-signature table."""
    header = (
        f"{'app':24} {'parties':>7} {'cv':>6} {'fano':>6} {'msg/pair':>9} "
        f"{'B/pair':>7} {'deadline':>8} {'F½util (±std)':>15} {'ΔF':>6} "
        f"{'stale½(ms, ±std)':>18} "
        f"{'stale½r(ms)':>11}"
    )
    lines = [header, "-" * len(header)]
    seeded = False
    for s in signatures:
        t = s.trace
        half_ms, half_ms_std, seed_note = _half_life_ms(s)
        half_ms_r = (
            s.staleness_halflife_range * 1e3 if s.staleness_halflife_range is not None else None
        )
        half_cell = _fmt_pm(half_ms, half_ms_std, ".3f")
        if seed_note:
            half_cell = "~" + half_cell + seed_note
            seeded = True
        lines.append(
            f"{s.app:24} {t.n_parties:>7} {t.request_cv:>6.2f} {t.fano_factor:>6.2f} "
            f"{t.msgs_per_pair:>9.2f} {t.bytes_per_pair:>7.2f} "
            f"{t.deadline_fraction:>8.2f} "
            f"{_fmt_pm(s.fidelity_threshold, s.fidelity_threshold_std, '.3f'):>15} "
            f"{_fmt(s.fidelity_range, '.2f'):>6} "
            f"{half_cell:>18} "
            f"{_fmt(half_ms_r, '.3f'):>11}"
        )
    if seeded:
        lines.append(
            "~ = the mean curve does not cross; value is the median over the "
            "(crossing/total) seeds that do."
        )
    return "\n".join(lines)


def _fmt_tex(value: float | None, spec: str) -> str:
    """LaTeX cells use `---`, not the Unicode dash the text table uses."""
    return format(value, spec) if value is not None else "---"


def _tex_escape(name: str) -> str:
    return name.replace("_", r"\_")


def render_latex(signatures: list[AppSignature]) -> str:
    """The same table as a booktabs `tabular`, for \\input{} into a paper.

    Emits the tabular only — no table environment, caption or label — so the
    surrounding float stays in the manuscript and only the numbers are generated.
    Requires booktabs and a \\code macro, both of which the manuscript defines.
    """
    head = [
        "% Generated by `qnetbench characterize --out`. Do not edit by hand.",
        "% Requires: booktabs (\\toprule etc.) and a \\code{} macro.",
        r"\begin{tabular}{@{}lrrrrrrrrrr@{}}",
        r"\toprule",
        "Application & parties & $cv$ & Fano & msg/pair & B/pair & deadline & "
        r"$F_{1/2}$ & $\Delta_F$ & $t_{1/2}$ (ms) & $t_{1/2}^{r}$ \\",
        r"\midrule",
    ]
    rows = []
    seeded = False
    for s in signatures:
        t = s.trace
        half_ms, half_ms_std, seed_note = _half_life_ms(s)
        half_ms_r = (
            s.staleness_halflife_range * 1e3 if s.staleness_halflife_range is not None else None
        )
        if half_ms is None:
            half_cell = "---"
        elif seed_note:
            seeded = True
            half_cell = rf"$\sim${half_ms:.3f}{seed_note}"
        elif half_ms_std:
            half_cell = rf"{half_ms:.3f} $\pm$ {half_ms_std:.3f}"
        else:
            half_cell = f"{half_ms:.3f}"
        if s.fidelity_threshold is None:
            fid_cell = "---"
        elif s.fidelity_threshold_std:
            fid_cell = rf"{s.fidelity_threshold:.3f} $\pm$ {s.fidelity_threshold_std:.3f}"
        else:
            fid_cell = f"{s.fidelity_threshold:.3f}"
        rows.append(
            rf"\code{{{_tex_escape(s.app)}}} & {t.n_parties} & {t.request_cv:.2f} & "
            rf"{t.fano_factor:.2f} & {t.msgs_per_pair:.2f} & {t.bytes_per_pair:.2f} & "
            rf"{t.deadline_fraction:.2f} & "
            rf"{fid_cell} & {_fmt_tex(s.fidelity_range, '.2f')} & {half_cell} & "
            rf"{_fmt_tex(half_ms_r, '.3f')} \\"
        )
    tail = [r"\bottomrule", r"\end{tabular}"]
    if seeded:
        tail.append(
            "% $\\sim$ marks a half-life the mean curve does not resolve: the value is "
            "the median over the (crossing/total) seeds that do."
        )
    return "\n".join(head + rows + tail) + "\n"
