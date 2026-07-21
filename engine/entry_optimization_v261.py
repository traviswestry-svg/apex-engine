"""APEX 26.1 — Entry Optimization Engine (advisory, deterministic).

Answers "should we take this now, wait for a pullback, or pass?" and at what
price. Produces best entry price, patience/momentum/confirmation scores,
pullback/chase probabilities, liquidity quality, expected slippage, and an
overall entry confidence. It reuses 26.3 for liquidity/slippage. No orders;
``production_effect`` is ``NONE``.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional

from . import liquidity_slippage_v263 as liquidity

VERSION = "26.1.0_ENTRY_OPTIMIZATION"
SCHEMA_VERSION = "apex.entry_optimization.v261.v1"

ENTRY_ACTIONS = ("ENTER_NOW", "WAIT_FOR_PULLBACK", "SCALE_IN", "PASS")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _round(v: Any, p: int = 2) -> Optional[float]:
    return None if v is None else round(float(v), p)


def optimize(root: Optional[Mapping[str, Any]], *, contracts: int = 1) -> dict[str, Any]:
    root = root if isinstance(root, Mapping) else {}
    liq = liquidity.analyze(root, contracts=contracts)
    quote = _mapping(liq.get("quote"))
    mid = _number(quote.get("mid"))
    spread = _number(liq.get("spread_width"))
    spread_pct = _number(liq.get("spread_pct"), 0.0)

    momentum = _clamp(_number(_mapping(root.get("momentum")).get("score"), 50.0))
    confirmation = _clamp(_number(_mapping(root.get("multi_timeframe")).get("alignment_score"), 50.0))
    # Distance from a recent reference (VWAP/anchor) informs pullback room.
    anchor = _number(_mapping(root.get("market_state")).get("vwap")
                     or _mapping(root.get("market_state")).get("anchor"), mid)
    price = _number(_mapping(root.get("market_state")).get("spx") or mid, mid)
    extension = abs(price - anchor) / anchor * 100 if anchor > 0 else 0.0

    # Scores.
    patience_score = _clamp(40 + extension * 3 + spread_pct * 2)      # more extended/wide -> be patient
    chase_score = _clamp(momentum - extension * 2)                    # strong momentum tempts chasing
    pullback_probability = _round(_clamp(30 + extension * 4) / 100, 3)
    chase_probability = _round(_clamp(momentum - 20) / 100, 3)

    # Best entry price: at mid when calm; below mid (for longs) when extended,
    # to encourage waiting for a pullback. Deterministic offset.
    direction = str(_mapping(root.get("market_state")).get("bias") or root.get("direction") or "").upper()
    sign = 1.0 if direction == "BULLISH" else -1.0 if direction == "BEARISH" else 0.0
    pullback_offset = spread * 0.5 + (extension / 100) * mid * 0.1
    best_entry_price = _round(mid - sign * pullback_offset, 4) if mid else None

    entry_confidence = _clamp(
        0.4 * confirmation + 0.3 * (100 - spread_pct * 4) + 0.3 * (momentum if momentum < 85 else 85 - (momentum - 85))
    )

    if extension > 6 and momentum > 75:
        action = "WAIT_FOR_PULLBACK"
    elif confirmation >= 60 and spread_pct <= 8 and momentum >= 55:
        action = "ENTER_NOW"
    elif confirmation >= 50:
        action = "SCALE_IN"
    else:
        action = "PASS"

    return {
        "ok": True,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "recommended_action": action,
        "best_entry_price": best_entry_price,
        "recommended_order_type": liq.get("recommended_order_type"),
        "recommended_limit_price": best_entry_price,
        "patience_score": _round(patience_score),
        "momentum_score": _round(momentum),
        "confirmation_score": _round(confirmation),
        "pullback_probability": pullback_probability,
        "chase_probability": chase_probability,
        "liquidity_quality": liq.get("liquidity_quality"),
        "expected_slippage": liq.get("estimated_slippage"),
        "fill_probability": liq.get("fill_probability"),
        "entry_confidence": _round(entry_confidence),
        "extension_pct": _round(extension, 3),
        "production_effect": "NONE",
    }


def status() -> dict[str, Any]:
    return {"status": "READY", "engine": "ENTRY_OPTIMIZATION", "version": VERSION,
            "actions": list(ENTRY_ACTIONS), "places_orders": False, "production_effect": "NONE"}
