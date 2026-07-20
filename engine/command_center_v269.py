"""APEX 26.9 Institutional Command Center + 26.10 Institutional Trader Mode.

Both are read-only aggregators that compose the governed 25.x + 26.x engines into
a single institutional workstation payload. They add no new intelligence, place
no orders, and mutate nothing. ``production_effect`` is ``NONE``.

26.9 Command Center: the execution-desk view (readiness, size, contract,
liquidity, execution score, risk, open trades, trade story, broker status,
promotion status, learning status).

26.10 Trader Mode: the flagship full-platform view — everything in Command
Center plus decision integrity, reasoning, forecast, confidence, replay,
execution review, learning queue, promotion queue, and system/broker/provider
health.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from . import institutional_decision_integrity_v250 as integrity

VERSION = "26.9_26.10_COMMAND_CENTER_TRADER_MODE"
SCHEMA_VERSION = "apex.command_center.v269_v2610.v1"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _safe(fn: Callable, *args, **kwargs) -> Any:
    """Call an optional engine function, returning None (with a note) on failure."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # aggregators degrade gracefully, never crash
        return {"unavailable": True, "reason": str(exc)}


def _optional(module_name: str):
    try:
        import importlib
        return importlib.import_module(f"engine.{module_name}")
    except Exception:
        try:
            import importlib
            return importlib.import_module(f".{module_name}", package="engine")
        except Exception:
            return None


def build_command_center(payload: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    root = payload if isinstance(payload, Mapping) else {}

    execution = _optional("execution_intelligence_core_v260")
    contract = _optional("contract_intelligence_v262")
    liquidity = _optional("liquidity_slippage_v263")
    sizing = _optional("position_sizing_v264")
    story = _optional("trade_story_v266")
    broker = _optional("broker_intelligence_v267")
    exec_review = _optional("execution_review_v268")
    validation = _optional("institutional_validation_promotion_v255")
    review = _optional("institutional_decision_review_v254")

    plan = _safe(execution.build_execution_plan, root) if execution else None
    plan_body = _mapping(_mapping(plan).get("execution_plan"))

    panels = {
        "execution_readiness": _mapping(plan_body.get("readiness")).get("state") if plan_body else None,
        "position_size": _mapping(plan_body.get("position_sizing")).get("recommended_contracts") if plan_body
        else (_safe(sizing.size, root).get("recommended_contracts") if sizing else None),
        "contract_recommendation": (_safe(contract.recommend, root).get("recommended_structure")
                                    if contract else None),
        "liquidity": (_safe(liquidity.analyze, root).get("liquidity_quality") if liquidity else None),
        "risk": {
            "estimated_dollar_risk": _mapping(plan_body.get("position_sizing")).get("estimated_dollar_risk")
            if plan_body else None,
            "max_risk_per_trade": _mapping(plan_body.get("position_sizing")).get("max_risk_per_trade")
            if plan_body else None,
        },
        "open_trades": len([t for t in (_mapping(root.get("portfolio")).get("open_trades") or [])]),
        "trade_story": _mapping(_safe(story.build_story, root)).get("story") if story else None,
        "broker_status": _mapping(_safe(broker.build_broker_view, root)).get("broker_health") if broker else None,
        "promotion_status": (_mapping(_safe(validation.promotion_overview, root)).get("engines")
                             if validation else None),
        "learning_status": (_mapping(_safe(review.list_recommendations, "PROPOSED")).get("count")
                            if review else None),
    }
    # Execution score if a completed trade is present.
    if exec_review and _mapping(root.get("completed_trade")):
        panels["execution_score"] = _mapping(_safe(exec_review.review, root.get("completed_trade"))).get("execution_score")

    return {
        "ok": True,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "view": "COMMAND_CENTER",
        "panels": panels,
        "guardrails": {"places_orders": False, "read_only": True, "confirmation_gated": True},
        "production_effect": "NONE",
    }


def build_trader_mode(payload: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    root = payload if isinstance(payload, Mapping) else {}
    decision = integrity.evaluate_decision(root)
    d = _mapping(decision.get("decision"))

    reasoning = _optional("institutional_reasoning_v251")
    forecast = _optional("decision_outcome_forecast_v252")
    calibration = _optional("adaptive_confidence_calibration_v253")
    review = _optional("institutional_decision_review_v254")
    validation = _optional("institutional_validation_promotion_v255")
    broker = _optional("broker_intelligence_v267")

    command_center = build_command_center(root)

    trader = {
        "decision_integrity": {
            "direction": d.get("direction"),
            "execution_eligibility": d.get("execution_eligibility"),
            "integrity_adjusted_confidence": d.get("integrity_adjusted_confidence"),
            "evidence_health": _mapping(decision.get("evidence_health")).get("state"),
        },
        "reasoning": (_mapping(_safe(reasoning.build_reasoning, root).get("reasoning")).get("thesis")
                      if reasoning else None),
        "forecast": (_mapping(_safe(forecast.build_forecast, root).get("forecast")).get("expected_path")
                     if forecast else None),
        "confidence": (_mapping(_mapping(_safe(calibration.build_calibration, root).get("calibration"))
                                .get("confidence_layers")).get("final_calibrated_confidence")
                       if calibration else None),
        "execution": command_center["panels"],
        "learning_queue": (_mapping(_safe(review.list_recommendations, "PROPOSED")).get("count")
                           if review else None),
        "promotion_queue": (_mapping(_safe(validation.promotion_overview, root)).get("engines")
                            if validation else None),
        "system_health": {
            "provider_health": _mapping(decision.get("evidence_health")).get("state"),
            "broker_health": _mapping(_safe(broker.build_broker_view, root)).get("broker_health")
            if broker else None,
        },
    }

    return {
        "ok": True,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "view": "INSTITUTIONAL_TRADER_MODE",
        "trader_mode": trader,
        "guardrails": {"places_orders": False, "read_only": True, "confirmation_gated": True,
                       "aggregator_only": True},
        "production_effect": "NONE",
    }


def status() -> dict[str, Any]:
    return {"status": "READY", "engine": "COMMAND_CENTER_TRADER_MODE", "version": VERSION,
            "views": ["COMMAND_CENTER", "INSTITUTIONAL_TRADER_MODE"],
            "places_orders": False, "read_only": True, "production_effect": "NONE"}
