"""APEX Trade Director Phase 39 — Subminute Execution Engine.

Uses 15-second and 30-second evidence only after a higher-timeframe setup exists.
It provides advisory entry/exit timing for 1–3 minute SPX option-premium scalps.
No broker action is ever submitted by this module.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _direction(value: Any) -> str:
    text = str(value or "NEUTRAL").upper()
    if text in {"CALL", "LONG", "BULLISH", "BUY"}:
        return "CALL"
    if text in {"PUT", "SHORT", "BEARISH", "SELL"}:
        return "PUT"
    return "NEUTRAL"


def _bar_metrics(bars: Iterable[Mapping[str, Any]], direction: str) -> Dict[str, Any]:
    rows = [dict(x) for x in bars if isinstance(x, Mapping)][-8:]
    if not rows:
        return {"coverage": 0, "aligned_close_pct": 0.0, "impulse_score": 0.0,
                "stall_score": 0.0, "reversal_score": 0.0, "bars_used": 0}

    aligned = 0
    impulses = []
    stalls = []
    reversals = []
    volumes = [_num(x.get("volume")) for x in rows]
    avg_vol = sum(volumes) / len(volumes) if any(volumes) else 0.0

    for bar in rows:
        o, h, l, c = (_num(bar.get(k)) for k in ("open", "high", "low", "close"))
        rng = max(0.0001, h - l)
        body = abs(c - o)
        upper = max(0.0, h - max(o, c))
        lower = max(0.0, min(o, c) - l)
        vol_ratio = (_num(bar.get("volume")) / avg_vol) if avg_vol > 0 else 1.0
        is_aligned = c > o if direction == "CALL" else c < o
        if is_aligned:
            aligned += 1
        close_location = (c - l) / rng if direction == "CALL" else (h - c) / rng
        impulse = 45.0 * (body / rng) + 35.0 * close_location + 20.0 * min(1.5, vol_ratio) / 1.5
        rejection_wick = upper / rng if direction == "CALL" else lower / rng
        adverse_body = (c < o) if direction == "CALL" else (c > o)
        stall = 55.0 * rejection_wick + 25.0 * (1.0 - body / rng) + 20.0 * (1.0 if vol_ratio < 0.75 else 0.0)
        reversal = 60.0 * (1.0 if adverse_body else 0.0) + 40.0 * rejection_wick
        impulses.append(_clamp(impulse))
        stalls.append(_clamp(stall))
        reversals.append(_clamp(reversal))

    recent = min(3, len(rows))
    return {
        "coverage": 100,
        "aligned_close_pct": round(100.0 * aligned / len(rows), 1),
        "impulse_score": round(sum(impulses[-recent:]) / recent, 1),
        "stall_score": round(sum(stalls[-recent:]) / recent, 1),
        "reversal_score": round(sum(reversals[-recent:]) / recent, 1),
        "bars_used": len(rows),
    }


def evaluate_subminute_execution(
    *,
    setup: Optional[Mapping[str, Any]] = None,
    bars_15s: Optional[Iterable[Mapping[str, Any]]] = None,
    bars_30s: Optional[Iterable[Mapping[str, Any]]] = None,
    position: Optional[Mapping[str, Any]] = None,
    current_premium: Optional[float] = None,
) -> Dict[str, Any]:
    """Evaluate execution timing without allowing subminute bars to create direction."""
    s = dict(setup or {})
    p = dict(position or {})
    direction = _direction(s.get("direction") or p.get("side"))
    setup_valid = bool(s.get("setup_valid", False))
    risk_eligible = bool(s.get("risk_eligible", False))
    data_fresh = bool(s.get("data_fresh", False))
    spread_ok = bool(s.get("spread_ok", False))
    one_minute_score = _clamp(_num(s.get("one_minute_setup_score")))
    confidence = _clamp(_num(s.get("confidence")))

    m15 = _bar_metrics(bars_15s or [], direction)
    m30 = _bar_metrics(bars_30s or [], direction)
    coverage = min(m15["coverage"], m30["coverage"])
    micro_impulse = round(0.62 * m15["impulse_score"] + 0.38 * m30["impulse_score"], 1)
    micro_stall = round(0.62 * m15["stall_score"] + 0.38 * m30["stall_score"], 1)
    micro_reversal = round(0.62 * m15["reversal_score"] + 0.38 * m30["reversal_score"], 1)
    alignment = round(0.62 * m15["aligned_close_pct"] + 0.38 * m30["aligned_close_pct"], 1)

    gate_failures = []
    if direction == "NEUTRAL": gate_failures.append("Higher-timeframe direction is unavailable.")
    if not setup_valid: gate_failures.append("The 1-minute setup has not been validated.")
    if one_minute_score < 74: gate_failures.append("The 1-minute setup score is below 74.")
    if confidence < 75: gate_failures.append("Directional confidence is below 75.")
    if not data_fresh: gate_failures.append("Market data is stale or freshness is unconfirmed.")
    if not risk_eligible: gate_failures.append("Risk governance has not approved this setup.")
    if not spread_ok: gate_failures.append("Option spread quality is not acceptable for a fast scalp.")
    if coverage < 100: gate_failures.append("Both 15-second and 30-second bar evidence are required.")

    status = str(p.get("status") or "").upper()
    is_open = status == "OPEN"
    entry = _num(p.get("option_entry_price"))
    current = _num(current_premium if current_premium is not None else p.get("option_current_price"))
    premium_change = round(current - entry, 2) if is_open and entry > 0 and current > 0 else None
    target_low = max(0.25, _num(s.get("premium_target_low"), 1.0))
    target_high = max(target_low, _num(s.get("premium_target_high"), 3.0))
    max_hold_seconds = max(30, int(_num(s.get("max_hold_seconds"), 180)))
    held_seconds = max(0, int(_num(p.get("time_in_trade_seconds") or p.get("time_in_trade_s"))))

    if is_open:
        if premium_change is None:
            action, state, reason = "SYNC_PREMIUM", "AWAITING_PREMIUM", "Actual entry and current option premium are required."
        elif premium_change >= target_high:
            action, state, reason = "TAKE_PROFIT", "TARGET_MAX_REACHED", f"Premium expanded ${premium_change:.2f}, reaching the ${target_high:.2f} maximum objective."
        elif micro_reversal >= 65 or micro_stall >= 70:
            action = "EXIT_OR_TIGHTEN" if premium_change >= 0 else "EXIT_NOW"
            state = "MOMENTUM_FAILED" if premium_change < 0 else "MOMENTUM_STALLED"
            reason = "Subminute momentum is stalling or reversing before the 1-minute candle fully reflects it."
        elif premium_change >= target_low and micro_impulse < 58:
            action, state, reason = "TAKE_PROFIT", "TARGET_REACHED_IMPULSE_FADING", f"Premium gained ${premium_change:.2f} and immediate impulse is fading."
        elif held_seconds >= max_hold_seconds:
            action, state, reason = "EXIT_OR_REASSESS", "TIMEBOX_REACHED", "The governed 1–3 minute holding window has expired."
        elif micro_impulse >= 68 and micro_reversal < 45:
            action, state, reason = "HOLD_TIGHT", "MICRO_MOMENTUM_EXPANDING", "15-second and 30-second impulse remain aligned with the validated setup."
        else:
            action, state, reason = "PROTECT", "MOMENTUM_UNCONFIRMED", "The trade is active, but subminute expansion is not strong enough to relax protection."
    elif gate_failures:
        action, state, reason = "WAIT", "HIGHER_TIMEFRAME_GATE_BLOCKED", gate_failures[0]
    elif micro_reversal >= 55 or micro_stall >= 65:
        action, state, reason = "WAIT", "MICRO_REJECTION", "The setup exists, but subminute bars show rejection or stalled momentum."
    elif micro_impulse >= 70 and alignment >= 62:
        action, state, reason = "ENTRY_ELIGIBLE", "MICRO_TRIGGER_CONFIRMED", "The validated 1-minute setup has aligned 15-second and 30-second momentum confirmation."
    elif micro_impulse >= 58 and alignment >= 55:
        action, state, reason = "ARM_ENTRY", "MICRO_TRIGGER_FORMING", "Subminute momentum is building; require one more clean confirmation before entry."
    else:
        action, state, reason = "WAIT", "MICRO_TRIGGER_ABSENT", "The higher-timeframe setup is valid, but the precise entry trigger has not formed."

    execution_score = round(_clamp(
        0.30 * one_minute_score + 0.20 * confidence + 0.30 * micro_impulse +
        0.10 * alignment + 0.10 * (100.0 - micro_reversal)
    ), 1)
    return {
        "version": "PHASE_39",
        "advisory_only": True,
        "confirmation_gated": True,
        "broker_action": "NONE",
        "direction_source": "HIGHER_TIMEFRAME_ONLY",
        "subminute_role": "ENTRY_AND_EXIT_TIMING_ONLY",
        "direction": direction,
        "state": state,
        "action": action,
        "reason": reason,
        "execution_score": execution_score,
        "gate_failures": gate_failures,
        "metrics_15s": m15,
        "metrics_30s": m30,
        "micro_impulse_score": micro_impulse,
        "micro_stall_score": micro_stall,
        "micro_reversal_score": micro_reversal,
        "micro_alignment_pct": alignment,
        "premium_change": premium_change,
        "premium_target_range": {"low": target_low, "high": target_high},
        "holding_window": {"held_seconds": held_seconds, "max_seconds": max_hold_seconds},
        "execution_note": "Recommendation only. The trader must manually confirm every entry or exit.",
    }
