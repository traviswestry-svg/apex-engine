"""engine/common/format.py — APEX 8.0 shared formatting utilities."""
from __future__ import annotations


def fmt_pts(v: float, decimals: int = 2) -> str:
    """Format as index points: '+4.25' or '-1.50'."""
    return f"{v:+.{decimals}f}"


def fmt_m(v: float) -> str:
    """Format dollar value as $X.XM or $X.XB."""
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1_000_000_000:
        return f"{sign}${a/1_000_000_000:.1f}B"
    if a >= 1_000_000:
        return f"{sign}${a/1_000_000:.1f}M"
    return f"{sign}${a:,.0f}"


def fmt_pct(v: float, decimals: int = 1) -> str:
    return f"{v:.{decimals}f}%"


def fmt_price(v: float) -> str:
    return f"${v:,.2f}"
