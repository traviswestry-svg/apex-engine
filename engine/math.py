"""engine/math.py — APEX shared numeric helpers.

This module must never import from engine.math or from the package root.
It is imported very early by engine.__init__, so it must be dependency-light.
"""
from __future__ import annotations

import math as _math
from typing import Any, Optional


def sf(value: Any, default: float = 0.0) -> float:
    """Safe float conversion with NaN/Inf protection."""
    try:
        if value is None:
            return default
        v = float(value)
        if _math.isnan(v) or _math.isinf(v):
            return default
        return v
    except Exception:
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    return sf(value, default)


def clamp(value: Any, lo: float = 0.0, hi: float = 100.0) -> float:
    v = sf(value, lo)
    return max(lo, min(hi, v))


def pct_chg(current: Any, prior: Any, default: float = 0.0) -> float:
    c = sf(current, 0.0)
    p = sf(prior, 0.0)
    if p == 0:
        return default
    return round((c - p) / p * 100.0, 3)


def pts_dist(price: Any, level: Any) -> Optional[float]:
    p = sf(price, 0.0)
    l = sf(level, 0.0)
    if p <= 0 or l <= 0:
        return None
    return round(abs(p - l), 2)


def pct_dist(price: Any, level: Any) -> Optional[float]:
    p = sf(price, 0.0)
    l = sf(level, 0.0)
    if p <= 0 or l <= 0:
        return None
    return round(abs(p - l) / p * 100.0, 3)
