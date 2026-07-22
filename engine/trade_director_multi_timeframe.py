"""APEX Trade Director Phase 17 — Multi-Timeframe Intelligence.

Deterministic, cached-only timeframe hierarchy and alignment analysis. This
module never requests market data, starts workers, or interacts with a broker.
It accepts normalized or partially normalized timeframe snapshots and fails
closed when coverage is insufficient.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Dict, Iterable, Mapping, Optional

TIMEFRAMES = ("1W", "1D", "4H", "1H", "15M", "5M", "1M")
WEIGHTS = {"1W": 0.08, "1D": 0.16, "4H": 0.18, "1H": 0.18, "15M": 0.16, "5M": 0.14, "1M": 0.10}
ALIASES = {
    "W": "1W", "WEEK": "1W", "WEEKLY": "1W", "1W": "1W",
    "D": "1D", "DAY": "1D", "DAILY": "1D", "1D": "1D",
    "240": "4H", "240M": "4H", "4H": "4H",
    "60": "1H", "60M": "1H", "1H": "1H",
    "15": "15M", "15M": "15M",
    "5": "5M", "5M": "5M",
    "1": "1M", "1M": "1M",
}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    return str(value or "").strip()


def _tf(value: Any) -> str:
    return ALIASES.get(_text(value).upper().replace(" ", ""), "")


def _direction(value: Any) -> str:
    text = _text(value).upper().replace(" ", "_")
    if any(x in text for x in ("BULL", "UPTREND", "LONG", "CALL", "RISK_ON", "HIGHER")):
        return "BULLISH"
    if any(x in text for x in ("BEAR", "DOWNTREND", "SHORT", "PUT", "RISK_OFF", "LOWER")):
        return "BEARISH"
    if any(x in text for x in ("NEUTRAL", "BALANCED", "RANGE", "CHOP", "FLAT", "MIXED")):
        return "NEUTRAL"
    return "UNAVAILABLE"


def _infer_direction(row: Mapping[str, Any]) -> str:
    for key in ("direction", "trend", "bias", "state", "signal", "expected_path"):
        d = _direction(row.get(key))
        if d != "UNAVAILABLE":
            return d
    price = _f(row.get("price") or row.get("close"), 0)
    ema8 = _f(row.get("ema8") or row.get("ema_8"), 0)
    ema21 = _f(row.get("ema21") or row.get("ema_21"), 0)
    vwap = _f(row.get("vwap"), 0)
    if price and ema8 and ema21:
        if price > ema8 > ema21 and (not vwap or price >= vwap):
            return "BULLISH"
        if price < ema8 < ema21 and (not vwap or price <= vwap):
            return "BEARISH"
        return "NEUTRAL"
    return "UNAVAILABLE"


def _normalize_row(tf: str, row: Mapping[str, Any]) -> Dict[str, Any]:
    direction = _infer_direction(row)
    strength = _f(row.get("strength") or row.get("score") or row.get("confidence"), 50.0)
    if 0 <= strength <= 1:
        strength *= 100
    strength = max(0.0, min(100.0, strength))
    momentum = _direction(row.get("momentum") or row.get("momentum_state"))
    if momentum == "UNAVAILABLE":
        momentum = direction
    structure = _text(row.get("structure") or row.get("market_structure") or "UNKNOWN").upper()
    available = direction != "UNAVAILABLE"
    return {
        "timeframe": tf,
        "available": available,
        "direction": direction,
        "strength": round(strength, 1) if available else None,
        "momentum": momentum if available else "UNAVAILABLE",
        "structure": structure,
        "price": _f(row.get("price") or row.get("close"), 0) or None,
        "vwap": _f(row.get("vwap"), 0) or None,
        "ema8": _f(row.get("ema8") or row.get("ema_8"), 0) or None,
        "ema21": _f(row.get("ema21") or row.get("ema_21"), 0) or None,
        "source": _text(row.get("source") or "CACHED_APEX"),
    }


def _collect_rows(source: Any) -> Dict[str, Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}

    def visit(node: Any, hinted_tf: str = "") -> None:
        if isinstance(node, Mapping):
            explicit = _tf(node.get("timeframe") or node.get("interval") or node.get("tf") or hinted_tf)
            if explicit and any(k in node for k in ("direction", "trend", "bias", "state", "signal", "price", "close", "ema8", "ema_8")):
                found[explicit] = _normalize_row(explicit, node)
            for key, value in node.items():
                key_tf = _tf(key)
                if key_tf and isinstance(value, Mapping):
                    found[key_tf] = _normalize_row(key_tf, value)
                elif isinstance(value, (Mapping, list, tuple)):
                    visit(value, key_tf or explicit)
        elif isinstance(node, (list, tuple)):
            for item in node:
                visit(item, hinted_tf)

    visit(source)
    return found


def build_multi_timeframe_intelligence(
    context: Optional[Mapping[str, Any]],
    timeframe_data: Optional[Any] = None,
) -> Dict[str, Any]:
    """Build the Phase 17 hierarchy from supplied or cached timeframe data."""
    context = dict(context or {})
    rows = _collect_rows(timeframe_data if timeframe_data is not None else context)
    matrix = [rows.get(tf) or {"timeframe": tf, "available": False, "direction": "UNAVAILABLE", "strength": None, "momentum": "UNAVAILABLE", "structure": "UNKNOWN", "source": "UNAVAILABLE"} for tf in TIMEFRAMES]
    available = [r for r in matrix if r["available"]]
    coverage = len(available) / len(TIMEFRAMES) * 100.0

    bull = sum(WEIGHTS[r["timeframe"]] * (r["strength"] or 50) / 100 for r in available if r["direction"] == "BULLISH")
    bear = sum(WEIGHTS[r["timeframe"]] * (r["strength"] or 50) / 100 for r in available if r["direction"] == "BEARISH")
    neutral = sum(WEIGHTS[r["timeframe"]] * 0.5 for r in available if r["direction"] == "NEUTRAL")
    represented_weight = sum(WEIGHTS[r["timeframe"]] for r in available) or 1.0
    net = (bull - bear) / represented_weight
    alignment_score = max(0.0, min(100.0, 50.0 + net * 100.0))

    directional = [r for r in available if r["direction"] in ("BULLISH", "BEARISH")]
    dominant = "BULLISH" if bull > bear else "BEARISH" if bear > bull else "NEUTRAL"
    aligned_weight = max(bull, bear)
    opposing_weight = min(bull, bear)
    conflict_ratio = opposing_weight / max(0.001, aligned_weight + opposing_weight)

    higher = [r for r in matrix if r["timeframe"] in ("1W", "1D", "4H", "1H") and r["available"]]
    lower = [r for r in matrix if r["timeframe"] in ("15M", "5M", "1M") and r["available"]]
    higher_dirs = [r["direction"] for r in higher if r["direction"] != "NEUTRAL"]
    lower_dirs = [r["direction"] for r in lower if r["direction"] != "NEUTRAL"]
    higher_bias = max(set(higher_dirs), key=higher_dirs.count) if higher_dirs else "NEUTRAL"
    lower_bias = max(set(lower_dirs), key=lower_dirs.count) if lower_dirs else "NEUTRAL"

    strategy_gate = _text(((context.get("strategy_orchestration") or {}).get("decision_gate"))).upper()
    session_mode = _text(((context.get("session_intelligence") or {}).get("session") or {}).get("mode")).upper()
    blockers = []
    if strategy_gate == "STAND_DOWN" or session_mode == "STOP_TRADING":
        gate = "STAND_DOWN"
        blockers.append("Upstream strategy or session authority requires stand down")
    elif len(available) < 3 or not higher or not lower:
        gate = "DATA_LIMITED"
        blockers.append("At least one higher and one execution timeframe plus three total frames are required")
    elif conflict_ratio >= 0.34 or (higher_bias not in ("NEUTRAL", lower_bias) and lower_bias != "NEUTRAL"):
        gate = "TIMEFRAME_CONFLICT"
        blockers.append("Higher and execution timeframes disagree")
    elif dominant == "NEUTRAL" or abs(alignment_score - 50) < 10:
        gate = "WAIT_FOR_ALIGNMENT"
    else:
        gate = "ALIGNED"

    if gate == "ALIGNED" and lower_bias == dominant:
        timing = "ENTRY_WINDOW_OPEN"
    elif gate in ("STAND_DOWN", "TIMEFRAME_CONFLICT"):
        timing = "AVOID_ENTRY"
    else:
        timing = "WAIT_FOR_TRIGGER"

    confidence = min(96.0, max(0.0, abs(alignment_score - 50) * 1.7 + coverage * 0.35))
    conflict_items = []
    for r in available:
        if dominant in ("BULLISH", "BEARISH") and r["direction"] not in (dominant, "NEUTRAL"):
            conflict_items.append({"timeframe": r["timeframe"], "direction": r["direction"], "severity": "HIGH" if r["timeframe"] in ("1D", "4H", "1H") else "MEDIUM"})

    thesis = {
        "direction": higher_bias,
        "statement": (
            f"Higher-timeframe structure is {higher_bias.lower()}; execution frames are {lower_bias.lower()}."
            if higher else "Higher-timeframe thesis unavailable."
        ),
        "invalidation": "Reassess if 1H/4H direction flips or the execution stack loses alignment.",
    }
    effect = 0
    if gate == "ALIGNED": effect = 6 if confidence >= 70 else 3
    elif gate == "TIMEFRAME_CONFLICT": effect = -10
    elif gate == "DATA_LIMITED": effect = -5

    return {
        "version": "PHASE_17",
        "as_of": _now(),
        "mode": "CACHED_ONLY_MULTI_TIMEFRAME",
        "decision_gate": gate,
        "entry_timing": timing,
        "dominant_direction": dominant,
        "alignment_score": round(alignment_score, 1),
        "confidence": round(confidence, 1),
        "coverage_pct": round(coverage, 1),
        "higher_timeframe_bias": higher_bias,
        "execution_timeframe_bias": lower_bias,
        "timeframe_matrix": matrix,
        "conflicts": conflict_items,
        "thesis": thesis,
        "trade_director_effect": {
            "health_adjustment": effect,
            "sizing_posture": "NORMAL" if gate == "ALIGNED" and confidence >= 65 else "REDUCED" if gate not in ("STAND_DOWN", "TIMEFRAME_CONFLICT") else "ZERO",
            "advisory_only": True,
        },
        "blockers": blockers,
        "safety_note": "Phase 17 is cached-only and advisory. It cannot override Phase 9 risk limits, Phase 10 confirmation, Phase 14 STAND_DOWN, or Phase 16 execution controls.",
    }
