"""APEX 26.6 — Institutional Trade Story Engine (advisory, deterministic).

Composes a human-readable narrative over the governed 25.x + 26.x state: why the
trade exists, why it is being held, why it might scale, and why it would exit,
plus the current confidence, reasoning summary, and forecast. Read-only;
``production_effect`` is ``NONE``.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from . import institutional_decision_integrity_v250 as integrity

try:
    from . import decision_outcome_forecast_v252 as forecast_engine  # type: ignore
except Exception:  # pragma: no cover
    forecast_engine = None  # type: ignore
try:
    from . import adaptive_confidence_calibration_v253 as calibration_engine  # type: ignore
except Exception:  # pragma: no cover
    calibration_engine = None  # type: ignore
try:
    from . import dynamic_trade_management_v265 as management_engine  # type: ignore
except Exception:  # pragma: no cover
    management_engine = None  # type: ignore

VERSION = "26.6.0_INSTITUTIONAL_TRADE_STORY"
SCHEMA_VERSION = "apex.trade_story.v266.v1"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def build_story(payload: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    root = payload if isinstance(payload, Mapping) else {}
    decision = integrity.evaluate_decision(root)
    d = _mapping(decision.get("decision"))
    explain = _mapping(decision.get("explainability"))
    direction = _text(d.get("direction"))
    eligibility = _text(d.get("execution_eligibility"))
    conf = d.get("integrity_adjusted_confidence")

    forecast = (forecast_engine.build_forecast(root)["forecast"] if forecast_engine else {})
    calibration = (calibration_engine.build_calibration(root)["calibration"]["confidence_layers"]
                   if calibration_engine else {})
    position = _mapping(root.get("position") or root.get("open_trade"))
    management = (management_engine.manage(root) if (management_engine and position) else {})

    thesis = _text(explain.get("thesis")) or f"{direction or 'No'} bias from the governed evidence stack."
    supporting = _list(explain.get("supporting_evidence"))
    opposing = _list(explain.get("opposing_evidence"))

    why_entered = (
        f"Entered on a {direction or 'neutral'} thesis: {thesis} "
        f"Integrity eligibility was {eligibility or 'UNKNOWN'} with adjusted confidence {conf}."
        if eligibility == "ELIGIBLE" else
        f"No entry: eligibility is {eligibility or 'UNKNOWN'} — {thesis}"
    )

    why_holding = None
    why_scaling = None
    why_exiting = None
    if position:
        actions = [a.get("action") for a in _list(management.get("recommended_actions"))]
        state = _mapping(management.get("position_state"))
        why_holding = (f"Holding: thesis intact, at {state.get('r_multiple')}R "
                       f"({state.get('pnl_pct')}% premium).")
        if "SCALE_OUT" in actions or "SCALE_IN" in actions:
            why_scaling = "Scaling: " + "; ".join(
                a.get("reason", "") for a in _list(management.get("recommended_actions"))
                if a.get("action") in {"SCALE_OUT", "SCALE_IN"})
        exit_actions = [a for a in _list(management.get("recommended_actions"))
                        if a.get("action") in {"STRUCTURE_EXIT", "TIME_EXIT", "VOLATILITY_EXIT",
                                               "MOVE_STOP", "PROFIT_LOCK"}]
        if exit_actions:
            why_exiting = "Exit watch: " + "; ".join(a.get("reason", "") for a in exit_actions)

    return {
        "ok": True,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "symbol": _text(root.get("symbol") or _mapping(root.get("market_state")).get("symbol") or "SPX"),
        "story": {
            "why_entered": why_entered,
            "why_holding": why_holding,
            "why_scaling": why_scaling,
            "why_exiting": why_exiting,
        },
        "updated_confidence": {
            "integrity_adjusted": conf,
            "final_calibrated": calibration.get("final_calibrated_confidence"),
        },
        "updated_reasoning": {
            "thesis": thesis,
            "supporting_count": len(supporting),
            "opposing_count": len(opposing),
            "counter_thesis": _text(explain.get("counter_thesis")) or None,
        },
        "updated_forecast": {
            "expected_path": forecast.get("expected_path"),
            "expected_move_points": forecast.get("expected_move_points"),
            "forecast_quality": forecast.get("forecast_quality"),
        },
        "production_effect": "NONE",
    }


def status() -> dict[str, Any]:
    return {"status": "READY", "engine": "INSTITUTIONAL_TRADE_STORY", "version": VERSION,
            "read_only": True, "production_effect": "NONE"}
