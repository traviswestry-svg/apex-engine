"""APEX 66.5.0 — Breadth Exhaustion & Recovery Engine.

Turns a real S&P 500 Bullish Percent Index observation into horizon-aware,
fail-closed context.  It never treats an oversold reading as a timed entry and
never receives execution authority.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import math
from typing import Any, Mapping, Optional, Sequence

VERSION = "66.9.0"
SCHEMA_VERSION = "apex.breadth_regime.v2"
FRESHNESS_VERSION = "apex.bpspx_freshness.v1"
DEFAULT_CURRENT_MAX_AGE_MINUTES = 24 * 60
DEFAULT_PRIOR_SETTLED_MAX_AGE_MINUTES = 4 * 24 * 60
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


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _freshness_governance(
    observed_at: Optional[str],
    *,
    now: datetime,
    session_open: Optional[bool],
    current_max_age_minutes: int,
    prior_settled_max_age_minutes: int,
) -> dict[str, Any]:
    observed = _parse_timestamp(observed_at)
    if observed is None:
        return {
            "version": FRESHNESS_VERSION,
            "state": "DATA_LIMITED",
            "usable": False,
            "reason": "bpspx_observed_at_missing_or_invalid",
            "age_minutes": None,
            "observed_at": observed_at,
            "current_max_age_minutes": current_max_age_minutes,
            "prior_settled_max_age_minutes": prior_settled_max_age_minutes,
        }

    age_minutes = max(0.0, (now - observed).total_seconds() / 60.0)
    if session_open is True:
        state = "CURRENT_SESSION" if age_minutes <= current_max_age_minutes else "STALE"
        usable = state == "CURRENT_SESSION"
    elif session_open is False:
        state = "PRIOR_SETTLED_SESSION" if age_minutes <= prior_settled_max_age_minutes else "STALE"
        usable = state == "PRIOR_SETTLED_SESSION"
    else:
        # When session state is unavailable, be conservative: only a current-age
        # observation may influence breadth. Weekend carry-forward requires the
        # caller to identify the market as closed.
        state = "CURRENT_SESSION" if age_minutes <= current_max_age_minutes else "STALE"
        usable = state == "CURRENT_SESSION"

    return {
        "version": FRESHNESS_VERSION,
        "state": state,
        "usable": usable,
        "reason": None if usable else "bpspx_observation_too_old",
        "age_minutes": round(age_minutes, 2),
        "observed_at": observed.isoformat(),
        "current_max_age_minutes": current_max_age_minutes,
        "prior_settled_max_age_minutes": prior_settled_max_age_minutes,
    }

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


def build_breadth_regime(
    context: Optional[Mapping[str, Any]] = None,
    *,
    now: Optional[datetime] = None,
    current_max_age_minutes: int = DEFAULT_CURRENT_MAX_AGE_MINUTES,
    prior_settled_max_age_minutes: int = DEFAULT_PRIOR_SETTLED_MAX_AGE_MINUTES,
) -> dict[str, Any]:
    root = dict(context or {})
    value, previous, history, source, observed_at = _extract(root)
    now_dt = now.astimezone(timezone.utc) if now and now.tzinfo else (now.replace(tzinfo=timezone.utc) if now else datetime.now(timezone.utc))
    now_iso = now_dt.isoformat()
    session_open_raw = root.get("market_open")
    if session_open_raw is None:
        session = root.get("session")
        if isinstance(session, Mapping):
            session_open_raw = session.get("is_open")
        elif isinstance(root.get("market_status"), Mapping):
            session_open_raw = root["market_status"].get("is_open")
    session_open = session_open_raw if isinstance(session_open_raw, bool) else None
    freshness = _freshness_governance(
        observed_at,
        now=now_dt,
        session_open=session_open,
        current_max_age_minutes=current_max_age_minutes,
        prior_settled_max_age_minutes=prior_settled_max_age_minutes,
    )
    base = {
        "ok": True, "version": VERSION, "schema_version": SCHEMA_VERSION,
        "as_of": now_iso, "execution_authority": "NONE",
        "guardrails": {
            "advisory_only": True, "automatic_entry": False,
            "oversold_is_not_confirmation": True,
            "may_not_block_valid_scalp": True, "fail_closed": True,
        },
    }
    if value is None or not 0 <= value <= 100:
        return {**base, "status": "DATA_LIMITED", "state": "DATA_LIMITED", "bpspx": None,
                "source": None, "freshness": freshness, "missing_data": ["bpspx"],
                "headline": "BPSPX feed required",
                "interpretation": "No real BPSPX observation is available; APEX will not infer one from price."}

    if not freshness["usable"]:
        return {
            **base,
            "status": freshness["state"],
            "state": "DATA_LIMITED",
            "bpspx": round(value, 2),
            "previous": round(previous, 2) if previous is not None else None,
            "source": source,
            "observed_at": observed_at,
            "freshness": freshness,
            "missing_data": ["current_bpspx_observation"],
            "headline": "BPSPX observation is not fresh enough for breadth influence",
            "interpretation": (
                f"BPSPX {value:.2f} is retained for diagnostics but freshness is "
                f"{freshness['state'].lower().replace('_', ' ')}; APEX suppresses breadth influence."
            ),
            "horizon_influence": {
                "SCALP": {"weight": 0.0, "effect": "DATA_LIMITED", "authority": "CONTEXT_ONLY"},
                "INTRADAY": {"weight": 0.0, "effect": "DATA_LIMITED", "authority": "CONTEXT_ONLY"},
                "SWING": {"weight": 0.0, "effect": "DATA_LIMITED", "authority": "CONTEXT_ONLY"},
            },
        }

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
        "direction": direction, "source": source, "observed_at": observed_at, "freshness": freshness,
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
