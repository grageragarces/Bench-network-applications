"""Small typed helpers for reading loosely-typed run configuration."""

from __future__ import annotations

from collections.abc import Mapping


def cfg_int(cfg: Mapping[str, object], key: str, default: int) -> int:
    val = cfg.get(key, default)
    if isinstance(val, bool) or not isinstance(val, (int, float, str)):
        return default
    return int(val)


def cfg_float(cfg: Mapping[str, object], key: str, default: float) -> float:
    val = cfg.get(key, default)
    if isinstance(val, bool) or not isinstance(val, (int, float, str)):
        return default
    return float(val)


def cfg_choice(cfg: Mapping[str, object], key: str, default: str, choices: tuple[str, ...]) -> str:
    """A string option that must be one of `choices`; anything else is an error."""
    val = cfg.get(key, default)
    if not isinstance(val, str) or val not in choices:
        raise ValueError(f"{key} must be one of {', '.join(choices)}, got {val!r}")
    return val
