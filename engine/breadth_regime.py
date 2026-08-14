"""APEX 66.5.0 — Breadth Exhaustion & Recovery Engine.

Turns a real S&P 500 Bullish Percent Index observation into horizon-aware,
fail-closed context.  It never treats an oversold reading as a timed entry and
never receives execution authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Mapping, Optional, Sequence

VERSION = "66.5.0"
SCHEMA_VERSION = "apex.breadth_regime.v1"
VALID_STATES = (
    "BROAD_RISK_ON", "NARROW_RISK_ON", "NEUTRAL", "BREADTH_DETERIORATION",
    "BROAD_RISK_OFF", "CAPITULATION", "EARLY_RECOVERY", "CONFIRMED_RECOVERY",
    "DATA_LIMITED",
)


def _number(value: Any) -> Optional[float]:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _direction(current: float, previous: Optional[float], history: Sequence[float]) -> str:
    reference = previous
    if reference is None and len(history) >= 2:
        reference = history[-2]
    if reference is None:
        return "UNKNOWN"
    delta = current - reference
    return "RISING" if delta >= 0.5 else "FALLING" if delta <= -0.5 else "FLAT"


def _extract(context: Mapping[str, Any]) -> tuple[Optional[float], Optional[float], list[float], str, Optional[str]]:
    candidates = [
        context.get("bpspx"),
        (context.get("breadth") or {}).get("bpspx") if isinstance(context.get("breadth"), Mapping) else None,
        (context.get("market_breadth") or {}).get("bpspx") if isinstance(context.get("market_breadth"), Mapping) else None,
        (context.get("breadth_regime") or {}).get("bpspx") if isinstance(context.get("breadth_regime"), Mapping) else None,
    ]
    value = next((_number(v) for v in candidates if _number(v) is not None), None)
    previous = _number(context.get("bpspx_previous"))
    raw_history = context.get("bpspx_history") or []
    history = [n for n in (_number(v) for v in raw_history) if n is not None]
    source = str(context.get("bpspx_source") or "canonical_context")
    observed_at = context.get("bpspx_observed_at")
    return value, previous, history, source, str(observed_at) if observed_at else None


def _state(value: float, direction: str, prior: Optional[float]) -> str:
    recovered_20 = prior is not None and prior < 20 <= value
    recovered_30 = prior is not None and prior < 30 <= value
    if recovered_30 and direction == "RISING":
        return "CONFIRMED_RECOVERY"
    if value <= 15:
        return "EARLY_RECOVERY" if direction == "RISING" else "CAPITULATION"
    if value < 30:
        return "EARLY_RECOVERY" if direction == "RISING" or recovered_20 else "BROAD_RISK_OFF"
    if value >= 70:
        return "BREADTH_DETERIORATION" if direction == "FALLING" else "BROAD_RISK_ON"
    if value >= 50:
        return "BREADTH_DETERIORATION" if direction == "FALLING" else "BROAD_RISK_ON"
    return "NEUTRAL" if direction != "FALLING" else "BREADTH_DETERIORATION"


def build_breadth_regime(context: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    root = dict(context or {})
    value, previous, history, source, observed_at = _extract(root)
    now = datetime.now(timezone.utc).isoformat()
    base = {
        "ok": True, "version": VERSION, "schema_version": SCHEMA_VERSION,
        "as_of": now, "execution_authority": "NONE",
        "guardrails": {
            "advisory_only": True, "automatic_entry": False,
            "oversold_is_not_confirmation": True,
            "may_not_block_valid_scalp": True, "fail_closed": True,
        },
    }
    if value is None or not 0 <= value <= 100:
        return {**base, "status": "DATA_LIMITED", "state": "DATA_LIMITED", "bpspx": None,
                "source": None, "missing_data": ["bpspx"],
                "headline": "BPSPX feed required",
                "interpretation": "No real BPSPX observation is available; APEX will not infer one from price."}

    direction = _direction(value, previous, history)
    prior = previous if previous is not None else (history[-2] if len(history) >= 2 else None)
    state = _state(value, direction, prior)
    confirmed = state == "CONFIRMED_RECOVERY"
    confidence = 55.0 if direction == "UNKNOWN" else 68.0
    if state in ("CAPITULATION", "EARLY_RECOVERY", "CONFIRMED_RECOVERY"):
        confidence += 8.0
    headline = {
        "CAPITULATION": "Extreme breadth washout — confirmation required",
        "EARLY_RECOVERY": "Breadth is recovering from a washed-out condition",
        "CONFIRMED_RECOVERY": "Breadth recovery confirmed above 30",
        "BREADTH_DETERIORATION": "Participation is deteriorating",
        "BROAD_RISK_OFF": "Broad participation remains risk-off",
        "BROAD_RISK_ON": "Broad participation supports risk-on",
        "NEUTRAL": "Breadth is mixed",
    }[state]
    scalp = "CAUTION_ON_LATE_SHORTS" if state in ("CAPITULATION", "EARLY_RECOVERY") else "CONTEXT_ONLY"
    intraday = "BULLISH_CONFIRMATION" if confirmed else "REVERSAL_WATCH" if state == "EARLY_RECOVERY" else "CONTEXT_ONLY"
    swing = "BULLISH" if confirmed else "BULLISH_WATCH" if state == "EARLY_RECOVERY" else "RISK_OFF" if state in ("CAPITULATION", "BROAD_RISK_OFF") else "NEUTRAL"
    return {
        **base, "status": "READY", "state": state, "bpspx": round(value, 2),
        "previous": round(prior, 2) if prior is not None else None,
        "direction": direction, "source": source, "observed_at": observed_at,
        "confidence": min(90.0, confidence), "recovery_confirmed": confirmed,
        "headline": headline,
        "interpretation": f"BPSPX {value:.2f} is {direction.lower()}; {state.lower().replace('_', ' ')} applies to breadth context, not entry timing.",
        "horizon_influence": {
            "SCALP": {"weight": 0.10, "effect": scalp, "authority": "CONTEXT_ONLY"},
            "INTRADAY": {"weight": 0.35, "effect": intraday, "authority": "CONFIRMATION_MODIFIER"},
            "SWING": {"weight": 0.85, "effect": swing, "authority": "REGIME_INPUT"},
        },
        "thresholds": {"oversold": 30, "extreme": 15, "overbought": 70, "confirmed_recovery": 30},
    }
