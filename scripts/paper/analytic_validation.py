"""Measured application quantities against their closed forms, across link fidelity.

Agreement here is what lets portability stand next to validity: if the engine gets these
wrong, no amount of cross-backend agreement would help. With Werner weight p = (4F - 1) / 3:

    qkd, bb84            QBER = 2(1 - F) / 3
    chsh                 S = 2 sqrt(2) p
    teleportation        P(recover) = (1 + p) / 2
    distributed_gate     P(truth table) = (1 + p) / 2
    bqc                  P(s = e) = (1 + p) / 2
    shared_randomness    P(agree) = (1 + p) / 2
    entanglement_swap    P(correlated) = (1 + p^2) / 2
    distillation         F' = (F^2 + b^2) / N and yield N / 2, with b = (1 - F) / 3,
                         N = (F + b)^2 + (2b)^2

    python scripts/paper/analytic_validation.py
"""

from __future__ import annotations

import math
import multiprocessing
import statistics
from collections.abc import Callable
from pathlib import Path

from qnetbench.apps import get_app
from qnetbench.characterize.provenance import write_atomic
from qnetbench.harness.runner import run_once
from qnetbench.topology import LinkModel, default_topology
from qnetbench.trace.events import AppOutcomeEvent, Event

FIDELITIES = (0.6, 0.7, 0.8, 0.9, 0.95, 0.99)
SEEDS = 16
OUT = Path(__file__).parent / "data" / "analytic_validation.txt"


def weight(f: float) -> float:
    return (4.0 * f - 1.0) / 3.0


def _distill_norm(f: float) -> float:
    b = (1.0 - f) / 3.0
    return (f + b) ** 2 + (2.0 * b) ** 2


def _distill_output(f: float) -> float:
    b = (1.0 - f) / 3.0
    return (f * f + b * b) / _distill_norm(f)


def _outcome(events: list[Event]) -> AppOutcomeEvent:
    outcomes = [e for e in events if isinstance(e, AppOutcomeEvent)]
    return next((e for e in outcomes if e.scores), outcomes[0])


def _payload(key: str) -> Callable[[list[Event]], float]:
    return lambda events: float(_outcome(events).payload[key])  # type: ignore[arg-type]


def _utility(events: list[Event]) -> float:
    return _outcome(events).utility


# application, quantity, how to read it, closed form, configuration
CASES: list[tuple[str, str, Callable[[list[Event]], float], Callable[[float], float], dict]] = [
    ("qkd", "QBER", _payload("qber"), lambda f: 2 * (1 - f) / 3, {"rounds": 2048}),
    ("bb84", "QBER", _payload("qber"), lambda f: 2 * (1 - f) / 3, {"rounds": 2048}),
    ("chsh", "S", _payload("S"), lambda f: 2 * math.sqrt(2) * weight(f), {"rounds": 2048}),
    ("teleportation", "P(recover)", _utility, lambda f: (1 + weight(f)) / 2, {"rounds": 512}),
    ("distributed_gate", "P(truth)", _utility, lambda f: (1 + weight(f)) / 2, {"reps": 512}),
    ("bqc", "P(s=e)", _utility, lambda f: (1 + weight(f)) / 2, {"depth": 512}),
    ("shared_randomness", "P(agree)", _utility, lambda f: (1 + weight(f)) / 2, {"rounds": 2048}),
    ("entanglement_swap", "P(corr)", _utility, lambda f: (1 + weight(f) ** 2) / 2, {"rounds": 512}),
    (
        "distillation",
        "F out",
        _payload("distilled_quality"),
        _distill_output,
        {"rounds": 512, "control_rounds": 32},
    ),
    (
        "distillation",
        "yield",
        _payload("yield"),
        lambda f: _distill_norm(f) / 2,
        {"rounds": 512, "control_rounds": 32},
    ),
]


def _measure(args: tuple[int, float, int]) -> tuple[int, float, float]:
    index, fidelity, seed = args
    app, _, read, _, cfg = CASES[index]
    roles = get_app(app).roles()
    topology = default_topology(roles, link=LinkModel(1e-3, fidelity, 0.0))
    return index, fidelity, read(run_once(app, seed=seed, topology=topology, cfg=dict(cfg)))


def main() -> None:
    work = [(i, f, s) for i in range(len(CASES)) for f in FIDELITIES for s in range(SEEDS)]
    with multiprocessing.Pool() as pool:
        results = pool.map(_measure, work)
    values: dict[tuple[int, float], list[float]] = {}
    for index, fidelity, value in results:
        values.setdefault((index, fidelity), []).append(value)

    lines = [
        f"Measured against closed form, {SEEDS} seeds per cell, no spread in link fidelity.",
        "z is (measured - predicted) / standard error across seeds.",
        "",
        f"{'application':20}{'quantity':12}{'F':>6}{'predicted':>11}{'measured':>11}{'s.e.':>9}{'z':>7}",
    ]
    zs: list[float] = []
    for index, (app, quantity, _, predict, _) in enumerate(CASES):
        for fidelity in FIDELITIES:
            sample = values[(index, fidelity)]
            mean = statistics.fmean(sample)
            se = statistics.stdev(sample) / math.sqrt(len(sample))
            expected = predict(fidelity)
            z = (mean - expected) / se if se > 0 else 0.0
            zs.append(z)
            lines.append(
                f"{app:20}{quantity:12}{fidelity:>6.2f}{expected:>11.4f}{mean:>11.4f}{se:>9.4f}{z:>7.2f}"
            )
    within = sum(abs(z) <= 2 for z in zs)
    worst = max(abs(z) for z in zs)
    lines += [
        "",
        f"{len(zs)} cells: {within} within 2 s.e. ({within / len(zs):.0%}, about 95% expected), "
        f"largest |z| {worst:.2f}.",
    ]
    text = "\n".join(lines) + "\n"
    write_atomic(OUT, text)
    print(text)


if __name__ == "__main__":
    main()
