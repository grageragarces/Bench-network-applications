"""Small typed helpers for reading loosely-typed run configuration."""

from __future__ import annotations

from collections.abc import Mapping


def cfg_int(cfg: Mapping[str, object], key: str, default: int) -> int:
    val = cfg.get(key, default)
    if isinstance(val, bool) or not isinstance(val, (int, float, str)):
        return default
    return int(val)
