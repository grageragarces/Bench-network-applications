"""Demand-signature characterization (Deliverable 2)."""

from __future__ import annotations

from qnetbench.characterize import (
    characterize_app,
    characterize_trace,
    fidelity_curve,
    render_latex,
    render_table,
    staleness_curve,
)
from qnetbench.harness.runner import run_once


def test_trace_signature_captures_coupling_and_parties() -> None:
    # distributed_gate is classically coupled and bipartite; qkd is neither.
    dg = characterize_trace(run_once("distributed_gate", seed=0))
    qk = characterize_trace(run_once("qkd", seed=0))
    assert dg.msgs_per_pair > 1.0  # a classical round-trip per pair
    assert qk.msgs_per_pair < 0.1  # only end-of-run reconciliation
    assert dg.n_parties == qk.n_parties == 2


def test_trace_signature_flags_multipartite_and_deadline() -> None:
    an = characterize_trace(run_once("anonymous_transmission", seed=0))
    dg = characterize_trace(run_once("distributed_gate", seed=0))
    assert an.n_parties == 3  # GHZ across three parties
    assert dg.deadline_fraction == 1.0  # every request carries a deadline
    assert dg.min_staleness_tolerance is not None  # staleness-intolerant


def test_fidelity_curve_is_monotonic_for_a_thresholded_app() -> None:
    curve = fidelity_curve("qkd", [0.7, 0.8, 0.9, 1.0], seeds=range(4))
    assert curve.y[0] <= curve.y[-1]  # utility rises with fidelity
    assert curve.y[-1] > 0.0 and curve.y[0] == 0.0  # QKD collapses below its threshold


def test_staleness_curve_decays_utility() -> None:
    curve = staleness_curve(
        "distributed_gate", [0.0, 1e-3, 5e-3], coherence_time=1e-3, seeds=range(4)
    )
    assert curve.y[0] > curve.y[-1]  # older pairs deliver less utility


def test_characterize_app_produces_signature_and_table() -> None:
    sig, curves = characterize_app("qkd", seeds=range(4))
    assert sig.app == "qkd"
    assert sig.fidelity_threshold is not None  # QKD has a fidelity cliff
    assert len(curves.fidelity.x) == len(curves.fidelity.y) > 0
    table = render_table([sig])
    assert "qkd" in table


def test_seed_crossings_are_reported_when_the_mean_curve_does_not_cross() -> None:
    """A plateauing staleness curve used to yield a spread with no location: the
    aggregate half-life was None while `staleness_halflife_std` was not, so the
    table showed a dash and silently dropped what the seeds did resolve.

    Which applications plateau depends on the seed count, since the level is
    taken from the mean curve; `distilled_gate` does so at both 6 and 32 seeds.
    """
    sig, _ = characterize_app("distilled_gate", seeds=range(6))
    assert sig.staleness_halflife is None  # the mean curve plateaus above the level
    assert sig.staleness_halflife_seed_median is not None
    assert 0 < sig.staleness_halflife_seed_count <= sig.n_seeds == 6
    table = render_table([sig])
    assert "~" in table and f"/{sig.n_seeds}" in table


def test_signature_never_reports_a_spread_without_a_location() -> None:
    """The invariant the old code violated, over the apps that exercise both axes."""
    for app in ("qkd", "distillation", "teleportation"):
        sig, _ = characterize_app(app, seeds=range(4))
        for value, median, std in (
            (
                sig.fidelity_threshold,
                sig.fidelity_threshold_seed_median,
                sig.fidelity_threshold_std,
            ),
            (
                sig.staleness_halflife,
                sig.staleness_halflife_seed_median,
                sig.staleness_halflife_std,
            ),
        ):
            if std is not None:
                assert value is not None or median is not None, f"{app}: orphaned spread"


def test_render_latex_emits_a_row_per_app() -> None:
    sigs = [characterize_app(a, seeds=range(2))[0] for a in ("qkd", "six_state")]
    tex = render_latex(sigs)
    assert tex.count(r"\\") >= 3  # header + two rows
    assert r"\begin{tabular}" in tex and r"\bottomrule" in tex
    assert r"\code{six\_state}" in tex  # app names escaped for LaTeX
    assert "—" not in tex  # empty cells are ---, not a Unicode dash
