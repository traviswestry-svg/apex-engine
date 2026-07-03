"""engine/common/math.py — APEX 8.0 shared numeric utilities.

Single source of truth for all safe-float, clamp, distance calculations.
Replaces 16 duplicate _sf definitions across the codebase.
"""
from __future__ import annotations
import math
from typing import Any, Optional


def sf(v: Any, default: float = 0.0) -> float:
    """Safe float conversion — never raises, never returns NaN/Inf."""
    try:
        f = float(v) if v is not None else default
        return default if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return default


# Backwards-compatible alias used throughout engines
_sf = sf


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def pct_chg(current: float, prior: float) -> Optional[float]:
    """Percentage change. Returns None if prior is zero."""
    if prior == 0:
        return None
    return round((current - prior) / prior * 100, 4)


def pts_dist(a: float, b: float) -> Optional[float]:
    """Absolute point distance. Returns None if either is zero/invalid."""
    if a <= 0 or b <= 0:
        return None
    return round(abs(a - b), 4)


def pct_dist(price: float, level: float) -> Optional[float]:
    """Percentage distance from price to level."""
    if price <= 0 or level <= 0:
        return None
    return round(abs(price - level) / price * 100, 4)
