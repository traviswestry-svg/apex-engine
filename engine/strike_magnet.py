"""engine/strike_magnet.py — APEX 7.0 Strike Magnet Map Engine.

Identifies price magnet levels from gamma concentration, OI, call/put walls,
and max pain estimation. Uses existing GEX engine output — no new API calls.

A "magnet" is a strike level with high enough gamma/OI concentration that
price is likely to be drawn toward it (or pinned near it) into expiration.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


def _sf(v: Any, d: float = 0.0) -> float:
    try:
        f = float(v) if v is not None else d
        return d if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return d


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# ── Max pain estimation ───────────────────────────────────────────────────────

def _estimate_max_pain(
    call_wall: float,
    put_wall:  float,
    zero_gamma: float,
    price:     float,
) -> Optional[float]:
    """Estimate max pain as the midpoint of the gamma zone.

    True max pain requires full OI by strike. We approximate it as the
    midpoint between call wall and put wall — where dealer losses are
    minimized. Labels as estimated.
    """
    if call_wall <= 0 or put_wall <= 0:
        return None
    return round((call_wall + put_wall) / 2, 2)


# ── Magnet scoring ────────────────────────────────────────────────────────────

def _score_magnet(
    strike:      float,
    magnet_type: str,
    price:       float,
    gex_score:   float,
    dte:         float,
    minutes_open: int,
) -> float:
    """Score a magnet level 0–100 based on type, proximity, and time factors."""
    dist_pts = abs(price - strike)
    dist_pct = dist_pts / price * 100 if price > 0 else 5.0

    # Base score from type
    type_scores = {
        "CALL_WALL":     85,
        "PUT_WALL":      85,
        "ZERO_GAMMA":    75,
        "MAX_PAIN":      70,
        "GAMMA_NODE":    65,
        "HVN":           55,
    }
    base = type_scores.get(magnet_type, 50)

    # Proximity boost: closer = stronger magnet
    if dist_pct < 0.1:
        prox = 20
    elif dist_pct < 0.3:
        prox = 15
    elif dist_pct < 0.5:
        prox = 10
    elif dist_pct < 1.0:
        prox = 5
    else:
        prox = 0

    # Time decay boost: magnets strengthen near expiration
    if dte <= 0.25:
        time_boost = 15
    elif dte <= 1:
        time_boost = 8
    else:
        time_boost = 0

    # Afternoon boost (max pain gravity increases)
    if minutes_open >= 300:
        af_boost = 10
    elif minutes_open >= 180:
        af_boost = 5
    else:
        af_boost = 0

    # Gamma regime: positive gamma = stronger pinning
    gex_boost = (gex_score - 50) * 0.1 if gex_score > 50 else 0

    return _clamp(base + prox + time_boost + af_boost + gex_boost)


# ── Main builder ──────────────────────────────────────────────────────────────

def build_strike_magnets(
    *,
    gamma_regime:  Dict[str, Any],
    market_state:  Dict[str, Any],
    auction_intel: Optional[Dict[str, Any]] = None,
    dte:           float = 0.0,
    minutes_open:  int = 0,
) -> Dict[str, Any]:
    """Build the strike magnet map from existing engine outputs."""

    price      = _sf(market_state.get("price") or gamma_regime.get("stock_price"))
    call_wall  = _sf(gamma_regime.get("call_wall"))
    put_wall   = _sf(gamma_regime.get("put_wall"))
    zero_gamma = _sf(gamma_regime.get("zero_gamma") or gamma_regime.get("displayZeroGamma"))
    gex_score  = _sf(gamma_regime.get("gex_score"), 50.0)
    poc        = _sf(market_state.get("poc"))
    vah        = _sf(market_state.get("vah"))
    val_       = _sf(market_state.get("val"))

    # HVN levels from auction intelligence
    hvn_list: List[float] = []
    if auction_intel:
        nodes = (auction_intel.get("nodes") or {}).get("nodes") or []
        hvn_list = [n["level"] for n in nodes if n.get("type") == "HVN"][:3]

    magnets: List[Dict[str, Any]] = []

    def add_magnet(strike: float, mtype: str, role: str):
        if strike <= 0:
            return
        dist = round(strike - price, 2)
        side = "ABOVE" if dist > 0 else "BELOW" if dist < 0 else "AT"
        score = _score_magnet(strike, mtype, price, gex_score, dte, minutes_open)
        bias = "RESISTANCE" if side == "ABOVE" else "SUPPORT"

        if mtype == "MAX_PAIN":
            bias = "PIN"
        elif mtype == "ZERO_GAMMA":
            bias = "REGIME_CHANGE"

        magnets.append({
            "strike":      round(strike, 2),
            "type":        mtype,
            "score":       round(score, 1),
            "distance":    dist,
            "side":        side,
            "magnet_bias": bias,
            "role":        role,
        })

    # Add known magnet levels
    add_magnet(call_wall,  "CALL_WALL",  "Maximum call OI — dealer resistance above")
    add_magnet(put_wall,   "PUT_WALL",   "Maximum put OI — dealer support below")
    add_magnet(zero_gamma, "ZERO_GAMMA", "Gamma regime crossover — dealer behavior changes here")
    add_magnet(poc,        "GAMMA_NODE", "Session POC — institutional value reference")
    add_magnet(vah,        "GAMMA_NODE", "Value Area High — acceptance/rejection level")
    add_magnet(val_,       "GAMMA_NODE", "Value Area Low — acceptance/rejection level")

    for hvn in hvn_list:
        add_magnet(hvn, "HVN", "High volume node — price tends to stall here")

    # Max pain estimate
    max_pain = _estimate_max_pain(call_wall, put_wall, zero_gamma, price)
    if max_pain:
        add_magnet(max_pain, "MAX_PAIN", "Estimated max pain — dealer loss minimization zone")

    # Sort by score descending, deduplicate close strikes (within 2pts)
    magnets.sort(key=lambda x: x["score"], reverse=True)
    deduped = []
    for m in magnets:
        if not any(abs(m["strike"] - d["strike"]) < 2 for d in deduped):
            deduped.append(m)

    deduped = deduped[:8]  # top 8

    # Pin risk assessment
    above = [m for m in deduped if m["side"] == "ABOVE"]
    below = [m for m in deduped if m["side"] == "BELOW"]
    nearest = deduped[0] if deduped else None

    # Pin risk: high if price is between walls and near max pain
    if max_pain and abs(price - max_pain) < 10 and gex_score >= 60:
        pin_risk = "HIGH"
        pin_note = (
            f"Price is within {abs(price - max_pain):.1f} points of estimated max pain ({max_pain}). "
            f"Positive gamma ({gex_score:.0f}) creates strong pinning conditions into expiration."
        )
    elif nearest and abs(nearest["distance"]) < 8:
        pin_risk = "MEDIUM"
        pin_note = (
            f"Price is {abs(nearest['distance']):.1f} points from the {nearest['type'].replace('_', ' ')} "
            f"at {nearest['strike']:.2f}. Moderate magnet gravity."
        )
    else:
        pin_risk = "LOW"
        pin_note = "No strong pin conditions. Price is free to move directionally."

    # What to watch sentence
    if above and below:
        watch = (
            f"Key magnets: {above[0]['strike']:.2f} ({above[0]['type'].replace('_', ' ')}) above, "
            f"{below[0]['strike']:.2f} ({below[0]['type'].replace('_', ' ')}) below. "
            f"{pin_note}"
        )
    else:
        watch = pin_note

    return {
        "available":       len(deduped) > 0,
        "version":         "7.0",
        "price":           round(price, 2),
        "magnets":         deduped,
        "pin_risk":        pin_risk,
        "pin_note":        pin_note,
        "nearest_magnet":  nearest["strike"] if nearest else None,
        "nearest_type":    nearest["type"] if nearest else None,
        "max_pain":        max_pain,
        "max_pain_method": "ESTIMATED_CALL_PUT_WALL_MIDPOINT",
        "watch":           watch,
        "call_wall":       call_wall,
        "put_wall":        put_wall,
        "zero_gamma":      zero_gamma,
        "gex_score":       round(gex_score, 1),
        "dte":             round(dte, 2),
        "quality_flags":   ["MAX_PAIN_ESTIMATED_NOT_CALCULATED"] if max_pain else [],
    }
