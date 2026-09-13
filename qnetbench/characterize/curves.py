"""Parametric demand-signature curves.

These need parameter sweeps rather than a single trace: the fidelity-sensitivity
curve (utility vs delivered fidelity) and the staleness-tolerance curve (utility vs
age of a pre-generated pair — directly feeding Issue #5). Both run on the reference
backend, which is deterministic and fast, and both are regenerable from source so
the characterization figures never drift from the code.
"""

from __future__ import annotations

import bisect

import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from qnetbench.apps import get_app
from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, Topology, line2, star


@dataclass
class Curve:
    x: list[float]
    y: list[float]  # mean utility at each x, across seeds
    xlabel: str
    ylabel: str = "utility"
    y_std: list[float] = field(default_factory=list)  # sample std across seeds at each x
    seed_utils: list[list[float]] = field(default_factory=list)  # seed_utils[i][s] = utility

    def insert(self, xi: float, utils: list[float]) -> None:
        """Insert one evaluated sweep point, keeping the curve sorted in x. Used by
        the bisection refinement, which adds points only where a crossing lies."""
        i = bisect.bisect_left(self.x, xi)
        self.x.insert(i, xi)
        self.y.insert(i, statistics.mean(utils))
        self.y_std.insert(i, _stdev(utils))
        self.seed_utils.insert(i, utils)

    def as_rows(self) -> list[dict[str, float]]:
        std = self.y_std or [0.0] * len(self.x)
        return [
            {self.xlabel: xi, self.ylabel: yi, f"{self.ylabel}_std": si}
            for xi, yi, si in zip(self.x, self.y, std, strict=True)
        ]


@dataclass
class CharacterizationCurves:
    app: str
    fidelity: Curve
    staleness: Curve
    fidelity_threshold: float | None = field(default=None)  # F at which utility crosses 0.5
    staleness_halflife: float | None = field(default=None)  # age at which utility halves
    # Std across seeds of the per-seed crossing point (each seed's own realization of
    # the curve, crossed against the aggregate curve's half-maximum level). None when
    # the threshold itself is undefined, or fewer than two seeds cross it.
    fidelity_threshold_std: float | None = field(default=None)
    staleness_halflife_std: float | None = field(default=None)
    # Utility gained across the swept fidelity range, u(F_max) - u(F_min). Reported
    # alongside the threshold because a threshold alone cannot distinguish an
    # application that is genuinely fidelity-insensitive from one whose utility
    # floor already sits above the crossing level.
    fidelity_range: float | None = field(default=None)
    # Staleness half-life measured from the curve's own asymptotic floor rather than
    # from zero, i.e. crossed against (u(0) + u_min)/2 instead of u(0)/2. Where a
    # curve plateaus just above u(0)/2 the absolute half-life is set by where a
    # nearly flat tail happens to graze the level and is badly conditioned; this
    # one is not. We report both rather than choosing, because the absolute figure
    # is the operationally meaningful one ("when has half the value gone?") and the
    # discrepancy between them is the honest measure of how well it is resolved.
    staleness_halflife_range: float | None = field(default=None)
    # Width of the bracketing interval the crossing was finally located in, after
    # bisection refinement. This is the resolution of the reported crossing, and it
    # is a separate and often larger source of error than the seed-to-seed spread:
    # on the coarse sweep alone, a crossing inside the first staleness interval was
    # reported as 0.10 ms with a seed spread of 0.00, when all the data supported
    # was "somewhere in (0, 0.2) ms".
    fidelity_threshold_bracket: float | None = field(default=None)
    staleness_halflife_bracket: float | None = field(default=None)


# Bisection stops once the crossing is bracketed this tightly. The fidelity
# tolerance matches the two decimals the paper quotes F_1/2 to; staleness is
# relative because the half-lives span two orders of magnitude, with an absolute
# floor so the shortest ones do not bisect forever.
# Seeds per sweep point. Raised from 8 after bisection refinement removed grid
# resolution as the limiting error and exposed seed noise underneath it: at 8
# seeds some applications' mean utility curves are not monotone through the
# crossing region, so the bisection was partly chasing noise.
SEEDS = 32

FIDELITY_TOL = 0.01
STALENESS_ABS_TOL = 1e-5  # 0.01 ms
STALENESS_REL_TOL = 0.05


def _fidelity_evaluator(app: str, seeds: Sequence[int]) -> Callable[[float], list[float]]:
    """Utilities at one delivered fidelity, one per seed."""
    roles = get_app(app).roles()

    def evaluate(f: float) -> list[float]:
        link = LinkModel(attempt_latency=1e-3, link_fidelity=f, fidelity_std=0.0)
        return _utilities(app, _topology_for(roles, link), seeds)

    return evaluate


def _staleness_evaluator(
    app: str, coherence_time: float, base_fidelity: float, seeds: Sequence[int]
) -> Callable[[float], list[float]]:
    """Utilities at one pair age, one per seed."""
    roles = get_app(app).roles()
    link = LinkModel(attempt_latency=1e-4, link_fidelity=base_fidelity, fidelity_std=0.0)
    topo = _topology_for(roles, link)

    def evaluate(age: float) -> list[float]:
        return _utilities(app, topo, seeds, pair_age=age, coherence_time=coherence_time)

    return evaluate


def _topology_for(roles: list[str], link: LinkModel) -> Topology:
    if len(roles) == 2:
        return line2(roles[0], roles[1], link=link)
    return star(roles[0], list(roles[1:]), link=link)


def _utilities(app: str, topo: Topology, seeds: Sequence[int], **run_kwargs: float) -> list[float]:
    return [
        compute_report(run_once(app, seed=s, topology=topo, **run_kwargs)).app_utility  # type: ignore[arg-type]
        for s in seeds
    ]


def _stdev(values: Sequence[float]) -> float:
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def fidelity_curve(
    app: str, fidelities: Sequence[float], seeds: Sequence[int] = range(SEEDS)
) -> Curve:
    evaluate = _fidelity_evaluator(app, seeds)
    x: list[float] = []
    y: list[float] = []
    y_std: list[float] = []
    seed_utils: list[list[float]] = []
    for f in fidelities:
        utils = evaluate(f)
        x.append(f)
        y.append(statistics.mean(utils))
        y_std.append(_stdev(utils))
        seed_utils.append(utils)
    return Curve(x=x, y=y, y_std=y_std, xlabel="delivered_fidelity", seed_utils=seed_utils)


def staleness_curve(
    app: str,
    ages: Sequence[float],
    coherence_time: float,
    base_fidelity: float = 1.0,
    seeds: Sequence[int] = range(SEEDS),
) -> Curve:
    evaluate = _staleness_evaluator(app, coherence_time, base_fidelity, seeds)
    x: list[float] = []
    y: list[float] = []
    y_std: list[float] = []
    seed_utils: list[list[float]] = []
    for age in ages:
        utils = evaluate(age)
        x.append(age)
        y.append(statistics.mean(utils))
        y_std.append(_stdev(utils))
        seed_utils.append(utils)
    return Curve(x=x, y=y, y_std=y_std, xlabel="pair_age_s", seed_utils=seed_utils)


def _first_crossing(x: list[float], y: list[float], level: float, rising: bool) -> float | None:
    """Linear-interpolated x at which y first crosses `level`."""
    for i in range(1, len(x)):
        y0, y1 = y[i - 1], y[i]
        crossed = (y0 < level <= y1) if rising else (y0 >= level > y1)
        if crossed and y1 != y0:
            frac = (level - y0) / (y1 - y0)
            return x[i - 1] + frac * (x[i] - x[i - 1])
    return None


def _bracket(
    x: list[float], y: list[float], level: float, rising: bool
) -> tuple[float, float] | None:
    """The first interval in which y crosses `level`. Mirrors _first_crossing's
    crossing test, so the two always agree on which interval is the answer."""
    for i in range(1, len(x)):
        y0, y1 = y[i - 1], y[i]
        crossed = (y0 < level <= y1) if rising else (y0 >= level > y1)
        if crossed and y1 != y0:
            return x[i - 1], x[i]
    return None


def _refine_crossing(
    curve: Curve,
    evaluate: Callable[[float], list[float]],
    level: float,
    rising: bool,
    *,
    abs_tol: float,
    rel_tol: float = 0.0,
    max_iter: int = 10,
) -> float | None:
    """Bisect the interval containing the crossing until it is narrower than the
    tolerance, evaluating the real simulation at each midpoint and inserting the
    result into `curve`.

    Without this the crossing is a linear interpolation across whatever the coarse
    sweep happened to bracket, which is only as good as the linearity assumption
    inside that interval. For a curve that falls from 1.0 to 0.005 across the first
    staleness interval that assumption is worthless: the interpolated answer lands
    near the interval midpoint by construction, and the seed spread around it is
    zero because every seed crosses in the same interval, so the number looks far
    better resolved than it is.

    The refined points join the curve, so the per-seed crossings and the plotted
    figure get the finer grid too. Returns the final bracket width (the resolution
    of the reported crossing), or None if the curve does not cross at all.
    """
    for _ in range(max_iter):
        br = _bracket(curve.x, curve.y, level, rising)
        if br is None:
            return None
        lo, hi = br
        if hi - lo <= max(abs_tol, rel_tol * abs(hi)):
            return hi - lo
        curve.insert((lo + hi) / 2, evaluate((lo + hi) / 2))
    br = _bracket(curve.x, curve.y, level, rising)
    return None if br is None else br[1] - br[0]


def _crossing_spread(
    x: list[float], seed_utils: list[list[float]], level: float, rising: bool
) -> float | None:
    """Std across seeds of the crossing point: each seed's own realization of the
    curve (one utility value per x, at that seed) is crossed against the same
    `level` used for the aggregate curve, giving one crossing point per seed."""
    if not seed_utils or not seed_utils[0]:
        return None
    n_seeds = len(seed_utils[0])
    crossings = []
    for s in range(n_seeds):
        row = [utils[s] for utils in seed_utils]
        c = _first_crossing(x, row, level, rising)
        if c is not None:
            crossings.append(c)
    return _stdev(crossings) if len(crossings) > 1 else None


def characterize_curves(
    app: str,
    *,
    coherence_time: float = 1e-3,
    seeds: Sequence[int] = range(SEEDS),
) -> CharacterizationCurves:
    fid = fidelity_curve(app, [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0], seeds)
    ages = [0.0, 2e-4, 5e-4, 1e-3, 2e-3, 5e-3, 1e-2]
    stale = staleness_curve(app, ages, coherence_time=coherence_time, seeds=seeds)

    # Thresholds are relative to each app's own utility *range*, so they compare
    # apps whose peak utility differs (e.g. QKD's utility is a key fraction < 0.5)
    # and, crucially, apps whose utility floor is nonzero. Crossing against fmax/2
    # would mark any application with u(F_min) > fmax/2 as having no threshold at
    # all, however strongly its utility depends on fidelity: entanglement swapping
    # runs 0.52 -> 1.00 across the swept range and would be reported as
    # fidelity-insensitive. Taking the midpoint of [fmin, fmax] removes the floor
    # and leaves apps with fmin = 0 (QKD and the other thresholded protocols)
    # exactly where they were.
    # Crossing levels are fixed from the coarse sweep and held there while the
    # curve is refined, so that adding points cannot move the target underneath us.
    fmax = max(fid.y) if fid.y else 0.0
    fmin = min(fid.y) if fid.y else 0.0
    frange = (fid.y[-1] - fid.y[0]) if fid.y else None
    level = (fmin + fmax) / 2
    resolved = bool(fid.y) and fmax > fmin
    threshold = None
    threshold_std = None
    threshold_bracket = None
    if resolved:
        threshold_bracket = _refine_crossing(
            fid, _fidelity_evaluator(app, seeds), level, rising=True, abs_tol=FIDELITY_TOL
        )
        threshold = _first_crossing(fid.x, fid.y, level, rising=True)
        threshold_std = _crossing_spread(fid.x, fid.seed_utils, level, rising=True)

    half = None
    half_std = None
    half_range = None
    half_bracket = None
    if stale.y and stale.y[0] > 0:
        stale_eval = _staleness_evaluator(app, coherence_time, 1.0, seeds)
        smin = min(stale.y)
        half_bracket = _refine_crossing(
            stale, stale_eval, stale.y[0] / 2, rising=False,
            abs_tol=STALENESS_ABS_TOL, rel_tol=STALENESS_REL_TOL,
        )
        half = _first_crossing(stale.x, stale.y, stale.y[0] / 2, rising=False)
        half_std = _crossing_spread(stale.x, stale.seed_utils, stale.y[0] / 2, rising=False)
        if stale.y[0] > smin:
            # Refined to the same tolerance, on the same (now denser) curve.
            _refine_crossing(
                stale, stale_eval, (stale.y[0] + smin) / 2, rising=False,
                abs_tol=STALENESS_ABS_TOL, rel_tol=STALENESS_REL_TOL,
            )
            half_range = _first_crossing(stale.x, stale.y, (stale.y[0] + smin) / 2, rising=False)
    return CharacterizationCurves(
        app=app,
        fidelity=fid,
        staleness=stale,
        fidelity_threshold=threshold,
        fidelity_range=frange,
        staleness_halflife=half,
        staleness_halflife_range=half_range,
        fidelity_threshold_std=threshold_std,
        staleness_halflife_std=half_std,
        fidelity_threshold_bracket=threshold_bracket,
        staleness_halflife_bracket=half_bracket,
    )
