from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


def _m(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _u(value: Any) -> str:
    return str(value or "").strip().upper()


def _direction(value: Any) -> str:
    x = _u(value)
    if any(k in x for k in ("BULL", "CALL", "UP", "LONG")):
        return "BULLISH"
    if any(k in x for k in ("BEAR", "PUT", "DOWN", "SHORT")):
        return "BEARISH"
    return "NEUTRAL"


def evaluate_dynamic_state_policy(
    snapshot: Optional[Mapping[str, Any]],
    *,
    direction: Any,
    dynamic_state: Optional[Mapping[str, Any]] = None,
    prior_state: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    s = dict(snapshot or {})
    ds = _m(dynamic_state or s.get("dynamic_state"))
    event_phase = _m(_m(s.get("event_intelligence")).get("event_phase"))
    residual = _m(ds.get("residual_pressure"))
    gamma_term = _m(ds.get("gamma_term_structure"))

    result = {
        "threshold_adjustment_points": 0,
        "conviction_penalty_points": 0,
        "consensus_penalty_points": 0,
        "watch_only": False,
        "suppress_new_alerts": False,
        "warnings": [],
    }

    trade_direction = _direction(direction)
    residual_direction = _direction(residual.get("direction"))
    if residual.get("available") and residual.get("unresolved") and residual_direction in {"BULLISH", "BEARISH"} and trade_direction in {"BULLISH", "BEARISH"} and residual_direction != trade_direction:
        result["conviction_penalty_points"] += 4
        result["warnings"].append("RESIDUAL_PRESSURE_OPPOSES_DIRECTION")

    if gamma_term.get("available") and gamma_term.get("term_divergence"):
        result["threshold_adjustment_points"] += 3
        result["consensus_penalty_points"] += 3
        result["conviction_penalty_points"] += 3
    if gamma_term.get("available") and gamma_term.get("near_term_fragility"):
        result["conviction_penalty_points"] += 3

    active_position = bool((prior_state or {}).get("active") or s.get("position_active"))
    phase = _u(event_phase.get("phase"))
    if phase == "RELEASE" and not active_position:
        result["suppress_new_alerts"] = True
        result["warnings"].append("EVENT_RELEASE_NEW_ALERT_SUPPRESSION")
    elif phase == "PRICE_DISCOVERY" and not active_position:
        result["watch_only"] = True
        result["threshold_adjustment_points"] += 8

    return result
