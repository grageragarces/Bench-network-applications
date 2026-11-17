"""Compare two traces, allowing for rounding-level differences in floats.

Byte equality is too strict a test of reproducibility across environments. The same
run under numpy 1.26 and numpy 2.5 can differ in the last bit of a sampled fidelity
while every event, measurement and outcome is the same. This module separates that
case from a real difference: traces are *equivalent* when they hold the same events
in the same order and their floats agree to within a tolerance.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import TypeAdapter

from qnetbench.trace.events import Event

_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)

# Absolute floor for values at or near zero, where a relative tolerance means nothing.
_ABS_TOL = 1e-15


@dataclass(frozen=True)
class TraceComparison:
    equivalent: bool
    max_relative_difference: float
    first_difference: str | None = None


class _Walk:
    def __init__(self, rel_tol: float) -> None:
        self.rel_tol = rel_tol
        self.max_rel = 0.0
        self.first_difference: str | None = None

    def _differ(self, path: str, x: object, y: object) -> None:
        if self.first_difference is None:
            self.first_difference = f"{path}: {x!r} != {y!r}"

    def compare(self, x: object, y: object, path: str) -> None:
        if isinstance(x, dict) and isinstance(y, dict):
            for key in x.keys() | y.keys():
                if key not in x or key not in y:
                    self._differ(f"{path}.{key}", x.get(key), y.get(key))
                else:
                    self.compare(x[key], y[key], f"{path}.{key}")
        elif isinstance(x, list) and isinstance(y, list):
            if len(x) != len(y):
                self._differ(f"{path} length", len(x), len(y))
            for i, (u, v) in enumerate(zip(x, y, strict=False)):
                self.compare(u, v, f"{path}[{i}]")
        elif _is_number(x) and _is_number(y):
            assert isinstance(x, (int, float)) and isinstance(y, (int, float))
            self._compare_numbers(float(x), float(y), path)
        elif x != y:
            self._differ(path, x, y)

    def _compare_numbers(self, x: float, y: float, path: str) -> None:
        if x == y:
            return
        scale = max(abs(x), abs(y))
        # 0.0 against 2e-16 is a ratio of 1 and means nothing, so values that are
        # themselves below the absolute floor do not count towards the largest ratio.
        if scale > _ABS_TOL and math.isfinite(scale):
            self.max_rel = max(self.max_rel, abs(x - y) / scale)
        if not math.isclose(x, y, rel_tol=self.rel_tol, abs_tol=_ABS_TOL):
            self._differ(path, x, y)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def compare_traces(
    a: Sequence[Event], b: Sequence[Event], *, rel_tol: float = 1e-12
) -> TraceComparison:
    """Compare traces event by event, in order, with floats held to `rel_tol`."""
    walk = _Walk(rel_tol)
    if len(a) != len(b):
        walk.first_difference = f"event count: {len(a)} != {len(b)}"
    for i, (x, y) in enumerate(zip(a, b, strict=False)):
        walk.compare(
            _ADAPTER.dump_python(x, mode="json"),
            _ADAPTER.dump_python(y, mode="json"),
            f"event[{i}]",
        )
    return TraceComparison(
        equivalent=walk.first_difference is None,
        max_relative_difference=walk.max_rel,
        first_difference=walk.first_difference,
    )
