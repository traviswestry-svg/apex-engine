"""engine/execution/price_mapper.py — SPX index ⇄ option premium conversion.

The single source of truth that lets the SPX price chart and the option premium chart
show the *same* trade levels on different axes. Entry/Stop/Breakeven/TP1–TP3 are stored
once and projected onto both axes through this module, so dragging a line in either pane
stays consistent in the other.

Model: a delta-based first-order map is used for the *linked* conversion so round-trips
are exact and reversible:
    Δpremium = delta · ΔSPX            (CALL delta > 0, PUT delta < 0 handles direction)
An optional second-order gamma term refines a one-way forward projection for display, but
the linked drag uses delta-only so premium→SPX→premium returns the same value.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

DEFAULT_PREMIUM_TICK = 0.05     # SPX option quotes tick at $0.05 (≤$3.00) / $0.10 (>$3.00)
DEFAULT_SPX_TICK = 0.25         # granularity for placing lines on the SPX price axis
_EPS = 1e-9


def snap(value: float, tick: float) -> float:
    if tick <= 0:
        return round(float(value), 4)
    return round(round(float(value) / tick) * tick, 4)


def premium_tick_for(premium: float) -> float:
    """SPX option minimum tick: $0.05 at or below $3.00, $0.10 above."""
    try:
        return 0.05 if float(premium) <= 3.0 else 0.10
    except Exception:
        return DEFAULT_PREMIUM_TICK


def premium_from_spx(spot: float, spx_level: float, base_premium: float, delta: float,
                     gamma: float = 0.0, premium_tick: Optional[float] = None) -> float:
    """Project an SPX index level onto the option premium axis.
    gamma defaults to 0 for exact reversibility; pass a real gamma only for a one-way
    display projection (it breaks round-trip invertibility)."""
    d_spx = float(spx_level) - float(spot)
    d_prem = delta * d_spx + 0.5 * gamma * d_spx * d_spx
    prem = max(0.0, float(base_premium) + d_prem)
    tick = premium_tick if premium_tick is not None else premium_tick_for(prem)
    return snap(prem, tick)


def spx_from_premium(spot: float, target_premium: float, base_premium: float, delta: float,
                     spx_tick: float = DEFAULT_SPX_TICK) -> Optional[float]:
    """Project an option premium onto the SPX index axis (delta-only inverse).
    Returns None when delta is ~0 (no usable mapping)."""
    if abs(delta) < 1e-4:
        return None
    d_spx = (float(target_premium) - float(base_premium)) / delta
    return snap(float(spot) + d_spx, spx_tick)


def project_level(value: float, source_axis: str, *, spot: float, base_premium: float,
                  delta: float, gamma: float = 0.0,
                  premium_tick: Optional[float] = None,
                  spx_tick: float = DEFAULT_SPX_TICK) -> Dict[str, Optional[float]]:
    """Given a level in one axis, return {'spx':…, 'premium':…} for both axes."""
    if source_axis == "spx":
        spx = snap(value, spx_tick)
        prem = premium_from_spx(spot, spx, base_premium, delta, gamma, premium_tick)
    elif source_axis == "premium":
        tick = premium_tick if premium_tick is not None else premium_tick_for(value)
        prem = max(0.0, snap(value, tick))
        spx = spx_from_premium(spot, prem, base_premium, delta, spx_tick)
    else:
        raise ValueError("source_axis must be 'spx' or 'premium'")
    return {"spx": spx, "premium": prem}


def project_levels(levels: Dict[str, float], source_axis: str, *, spot: float,
                   base_premium: float, delta: float, gamma: float = 0.0,
                   premium_tick: Optional[float] = None,
                   spx_tick: float = DEFAULT_SPX_TICK) -> Dict[str, Dict[str, Optional[float]]]:
    """Project a whole set of trade lines (ENTRY/STOP/BREAKEVEN/TP1/TP2/TP3) onto both
    axes at once. This is what the dual-pane chart calls after any drag."""
    out: Dict[str, Dict[str, Optional[float]]] = {}
    for tag, val in (levels or {}).items():
        if val is None:
            continue
        out[tag] = project_level(val, source_axis, spot=spot, base_premium=base_premium,
                                  delta=delta, gamma=gamma, premium_tick=premium_tick,
                                  spx_tick=spx_tick)
    return out


# Default bracket geometry (spec §6), midpoints of the stated ranges. Configurable by caller.
_DEFAULTS = {"stop_pct": -0.27, "tp1_pct": 0.25, "tp2_pct": 0.60, "tp3_pct": 1.00}


def suggest_bracket(base_premium: float, *, spot: float, delta: float, gamma: float = 0.0,
                    pct: Optional[Dict[str, float]] = None,
                    spx_tick: float = DEFAULT_SPX_TICK) -> Dict[str, Dict[str, Optional[float]]]:
    """Suggest initial Entry/Stop/Breakeven/TP1–TP3 lines from the entry premium, and
    project each onto both axes so the chart can place them immediately.
    Percentages are of the entry premium: stop −27%, TP1 +25%, TP2 +60%, TP3 +100%."""
    p = {**_DEFAULTS, **(pct or {})}
    prem_levels = {
        "ENTRY": base_premium,
        "BREAKEVEN": base_premium,
        "STOP": max(0.0, base_premium * (1 + p["stop_pct"])),
        "TP1": base_premium * (1 + p["tp1_pct"]),
        "TP2": base_premium * (1 + p["tp2_pct"]),
        "TP3": base_premium * (1 + p["tp3_pct"]),
    }
    return project_levels(prem_levels, "premium", spot=spot, base_premium=base_premium,
                          delta=delta, gamma=gamma, spx_tick=spx_tick)
