"""engine/format.py — APEX shared formatting helpers."""
from __future__ import annotations

from typing import Any

from .math import sf


def fmt_price(value: Any, decimals: int = 2) -> str:
    return f"{sf(value):,.{decimals}f}"


def fmt_pts(value: Any, decimals: int = 2) -> str:
    return f"{sf(value):,.{decimals}f} pts"


def fmt_pct(value: Any, decimals: int = 1) -> str:
    return f"{sf(value):,.{decimals}f}%"


def fmt_m(value: Any) -> str:
    v = sf(value)
    av = abs(v)
    sign = "-" if v < 0 else ""
    if av >= 1_000_000_000:
        return f"{sign}${av/1_000_000_000:.1f}B"
    if av >= 1_000_000:
        return f"{sign}${av/1_000_000:.1f}M"
    if av >= 1_000:
        return f"{sign}${av/1_000:.0f}K"
    return f"{sign}${av:.0f}"
