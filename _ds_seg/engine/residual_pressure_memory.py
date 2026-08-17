"""APEX — Residual Pressure Memory state machine.

Preserves unresolved directional pressure after price is contained at a level.
Pure/deterministic by design: callers may persist/pass the returned state on the
next cycle, avoiding hidden per-worker process state.
"""
from __future__ import annotations
from datetime import datetime, timezone
from math import exp
from typing import Any, Dict, Mapping, Optional

VERSION = "66.4.0_RESIDUAL_PRESSURE_MEMORY"


def _f(v: Any, d: float = 0.0) -> float:
    try: return float(v)
    except (TypeError, ValueError): return d


def evolve_residual_pressure(previous: Optional[Mapping[str, Any]], *, direction: str,
                             pressure_score: float, absorption_signal: str,
                             absorption_score: float, acceptance_state: str = "UNKNOWN",
                             level: Optional[Any] = None, price_response: float = 0.0,
                             now: Optional[datetime] = None, half_life_seconds: float = 300.0) -> Dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    prev = dict(previous or {})
    prior_remaining = _f(prev.get("remaining_pressure"))
    prior_time = prev.get("updated_at")
    elapsed = 0.0
    if prior_time:
        try:
            pt = datetime.fromisoformat(str(prior_time).replace("Z", "+00:00"))
            if pt.tzinfo is None: pt = pt.replace(tzinfo=timezone.utc)
            elapsed = max(0.0, (current - pt).total_seconds())
        except (TypeError, ValueError):
            elapsed = 0.0
    decayed = prior_remaining * exp(-0.69314718056 * elapsed / max(1.0, half_life_seconds))
    incoming = max(0.0, min(100.0, _f(pressure_score)))
    absorbed = str(absorption_signal or "").upper() in {"HIGH_ABSORPTION", "MODERATE_ABSORPTION", "BULLISH_ABSORPTION", "BEARISH_ABSORPTION"}
    accepted = str(acceptance_state or "").upper() in {"ACCEPTING", "ACCEPTED", "BREAK", "BREAKING"}
    opposed_response = (direction.upper() == "BULLISH" and price_response < 0) or (direction.upper() == "BEARISH" and price_response > 0)

    remaining = min(100.0, max(decayed, incoming * (0.75 if absorbed else 0.35)))
    if accepted and not absorbed:
        state = "RESOLVED"
        remaining *= 0.25
    elif absorbed or opposed_response:
        state = "RESIDUAL_PRESSURE" if remaining >= 20 else "CONTAINED"
    elif incoming >= 55:
        state = "ACTIVE"
    elif remaining >= 20:
        state = "RESIDUAL_PRESSURE"
    else:
        state = "RESOLVED"
        remaining = 0.0

    return {
        "version": VERSION, "state": state, "direction": direction.upper() or "UNKNOWN",
        "origin_level": level if level is not None else prev.get("origin_level"),
        "initial_pressure": round(max(_f(prev.get("initial_pressure")), incoming), 2),
        "remaining_pressure": round(remaining, 2), "decay_half_life_seconds": half_life_seconds,
        "absorption_signal": absorption_signal, "absorption_score": round(_f(absorption_score), 2),
        "acceptance_state": acceptance_state, "price_response": round(_f(price_response), 4),
        "unresolved": state in {"ACTIVE", "CONTAINED", "RESIDUAL_PRESSURE"},
        "updated_at": current.isoformat(),
    }
