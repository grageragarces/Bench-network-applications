"""Parametric demand-signature curves.

These need parameter sweeps rather than a single trace: the fidelity-sensitivity
curve (utility vs delivered fidelity) and the staleness-tolerance curve (utility vs
age of a pre-generated pair — directly feeding Issue #5). Both run on the reference
backend, which is deterministic and fast, and both are regenerable from source so
the characterization figures never drift from the code.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
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
    app: str, fidelities: Sequence[float], seeds: Sequence[int] = range(8)
) -> Curve:
    roles = get_app(app).roles()
    x: list[float] = []
    y: list[float] = []
    y_std: list[float] = []
    seed_utils: list[list[float]] = []
    for f in fidelities:
        link = LinkModel(attempt_latency=1e-3, link_fidelity=f, fidelity_std=0.0)
        utils = _utilities(app, _topology_for(roles, link), seeds)
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
    seeds: Sequence[int] = range(8),
) -> Curve:
    roles = get_app(app).roles()
    link = LinkModel(attempt_latency=1e-4, link_fidelity=base_fidelity, fidelity_std=0.0)
    topo = _topology_for(roles, link)
    x: list[float] = []
    y: list[float] = []
    y_std: list[float] = []
    seed_utils: list[list[float]] = []
    for age in ages:
        utils = _utilities(app, topo, seeds, pair_age=age, coherence_time=coherence_time)
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
    seeds: Sequence[int] = range(8),
) -> CharacterizationCurves:
    fid = fidelity_curve(app, [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0], seeds)
    ages = [0.0, 2e-4, 5e-4, 1e-3, 2e-3, 5e-3, 1e-2]
    stale = staleness_curve(app, ages, coherence_time=coherence_time, seeds=seeds)

    # Thresholds are relative to each app's own maximum utility, so they compare
    # apps whose peak utility differs (e.g. QKD's utility is a key fraction < 0.5).
    fmax = max(fid.y) if fid.y else 0.0
    threshold = _first_crossing(fid.x, fid.y, fmax / 2, rising=True) if fmax > 0 else None
    threshold_std = (
        _crossing_spread(fid.x, fid.seed_utils, fmax / 2, rising=True) if fmax > 0 else None
    )
    half = None
    half_std = None
    if stale.y and stale.y[0] > 0:
        half = _first_crossing(stale.x, stale.y, stale.y[0] / 2, rising=False)
        half_std = _crossing_spread(stale.x, stale.seed_utils, stale.y[0] / 2, rising=False)
    return CharacterizationCurves(
        app=app,
        fidelity=fid,
        staleness=stale,
        fidelity_threshold=threshold,
        staleness_halflife=half,
        fidelity_threshold_std=threshold_std,
        staleness_halflife_std=half_std,
    )
