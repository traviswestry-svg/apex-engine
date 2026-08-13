"""APEX Trade Director Phase 26 — Institutional Performance & Intelligence Command Center.

Observational diagnostics only. This module aggregates existing Phase 11–25 outputs,
archived learning records, and shadow-validation evidence. It never mutates strategy,
risk, authorization, lifecycle, policy, broker, or execution configuration.
"""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean
from typing import Any, Dict, Iterable, List, Mapping, Optional

from engine.trade_director_lifecycle_contracts import as_mapping, utc_now_iso
from engine.trade_director_institutional_learning import learning_history


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _age_seconds(timestamp: Any) -> Optional[float]:
    if not timestamp:
        return None
    try:
        text = str(timestamp).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def _status(score: float) -> str:
    return "GREEN" if score >= 85 else "YELLOW" if score >= 65 else "RED"


def _engine_row(name: str, phase: str, payload: Mapping[str, Any], *, expected_live: bool = False) -> Dict[str, Any]:
    p = as_mapping(payload)
    error = bool(p.get("error"))
    available = bool(p) and not error
    timestamp = p.get("as_of") or p.get("checked_at") or p.get("updated_at") or p.get("generated_at")
    age = _age_seconds(timestamp)
    freshness = 100.0
    if age is not None:
        freshness = 100.0 if age <= 30 else 85.0 if age <= 300 else 65.0 if age <= 1800 else 40.0
    elif expected_live:
        freshness = 55.0
    completeness_fields = [k for k, v in p.items() if v not in (None, "", [], {})]
    completeness = min(100.0, 40.0 + len(completeness_fields) * 5.0) if available else 0.0
    quality = _f(p.get("score") or p.get("confidence") or p.get("overall_score") or p.get("health_score"), 75.0 if available else 0.0)
    if quality <= 1.0 and quality > 0:
        quality *= 100.0
    score = 0.35 * (100.0 if available else 0.0) + 0.25 * freshness + 0.20 * completeness + 0.20 * _clamp(quality)
    if error:
        score = min(score, 25.0)
    return {
        "engine": name,
        "phase": phase,
        "status": _status(score),
        "health_score": round(score, 1),
        "available": available,
        "freshness_score": round(freshness, 1),
        "evidence_completeness": round(completeness, 1),
        "age_seconds": None if age is None else round(age, 1),
        "detail": str(p.get("error") or p.get("state") or p.get("mode") or p.get("learning_state") or p.get("validation_state") or "AVAILABLE"),
    }


def _records(records: Optional[Iterable[Mapping[str, Any]]] = None) -> List[Dict[str, Any]]:
    source = records if records is not None else learning_history(2000)
    return [dict(r) for r in source]


def build_performance_scorecards(records: Optional[Iterable[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    rows = _records(records)
    r_values = [_f(r.get("r_multiple"), 0.0) for r in rows]
    pnl = [_f(r.get("realized_pnl"), 0.0) for r in rows]
    wins = [x for x in r_values if x > 0]
    losses = [x for x in r_values if x < 0]
    n = len(rows)
    gross_profit = sum(x for x in pnl if x > 0)
    gross_loss = abs(sum(x for x in pnl if x < 0))
    running = peak = max_dd = 0.0
    for x in pnl:
        running += x
        peak = max(peak, running)
        max_dd = max(max_dd, peak - running)
    qualities = [_f(r.get("decision_quality") or as_mapping(r.get("learning_context")).get("overall_decision_quality"), 0.0) for r in rows]
    qualities = [q for q in qualities if q > 0]
    confidences = [_f(r.get("decision_confidence"), 0.0) for r in rows]
    calibration_errors = [abs(c - (100.0 if rv > 0 else 0.0)) for c, rv in zip(confidences, r_values) if c > 0]
    return {
        "sample_size": n,
        "win_rate_pct": round(len(wins) / n * 100.0, 1) if n else None,
        "expectancy_r": round(mean(r_values), 3) if r_values else None,
        "average_r": round(mean(r_values), 3) if r_values else None,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else (None if not gross_profit else 999.0),
        "realized_pnl": round(sum(pnl), 2),
        "maximum_drawdown": round(max_dd, 2),
        "average_decision_quality": round(mean(qualities), 1) if qualities else None,
        "calibration_error_points": round(mean(calibration_errors), 1) if calibration_errors else None,
        "positive_r_count": len(wins),
        "negative_r_count": len(losses),
    }


def build_drift_detection(records: Optional[Iterable[Mapping[str, Any]]] = None, *, recent_window: int = 20, baseline_window: int = 60) -> Dict[str, Any]:
    rows = _records(records)
    values = [_f(r.get("r_multiple"), 0.0) for r in rows]
    recent = values[-recent_window:]
    baseline = values[-(recent_window + baseline_window):-recent_window]
    alerts: List[Dict[str, Any]] = []
    recent_exp = mean(recent) if recent else 0.0
    base_exp = mean(baseline) if baseline else 0.0
    recent_wr = sum(1 for x in recent if x > 0) / len(recent) * 100.0 if recent else 0.0
    base_wr = sum(1 for x in baseline if x > 0) / len(baseline) * 100.0 if baseline else 0.0
    if baseline and recent_exp < base_exp - 0.25:
        alerts.append({"type": "EXPECTANCY_DRIFT", "severity": "RED" if recent_exp < base_exp - 0.5 else "YELLOW", "delta": round(recent_exp - base_exp, 3)})
    if baseline and recent_wr < base_wr - 10.0:
        alerts.append({"type": "WIN_RATE_DRIFT", "severity": "YELLOW", "delta_pct": round(recent_wr - base_wr, 1)})
    if len(rows) < recent_window:
        alerts.append({"type": "INSUFFICIENT_RECENT_SAMPLE", "severity": "YELLOW", "required": recent_window, "available": len(rows)})
    state = "DRIFT_DETECTED" if any(a.get("severity") == "RED" for a in alerts) else "WATCH" if alerts else "STABLE"
    return {
        "state": state,
        "recent_window": len(recent),
        "baseline_window": len(baseline),
        "recent_expectancy_r": round(recent_exp, 3) if recent else None,
        "baseline_expectancy_r": round(base_exp, 3) if baseline else None,
        "recent_win_rate_pct": round(recent_wr, 1) if recent else None,
        "baseline_win_rate_pct": round(base_wr, 1) if baseline else None,
        "alerts": alerts,
    }


def build_command_center(context: Optional[Mapping[str, Any]] = None, records: Optional[Iterable[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    ctx = dict(context or {})
    specs = [
        ("Session Intelligence", "11", "session_intelligence", True),
        ("Market Memory", "12", "market_memory", False),
        ("Cross-Asset Intelligence", "13", "cross_asset_intelligence", True),
        ("Strategy Orchestration", "14", "strategy_orchestration", True),
        ("Options Intelligence", "15", "options_intelligence", True),
        ("Execution Desk", "16", "execution_desk", True),
        ("Multi-Timeframe Intelligence", "17", "multi_timeframe_intelligence", True),
        ("Institutional Flow", "18", "flow_intelligence", True),
        ("Decision Committee", "19", "decision_intelligence", True),
        ("Authorization", "20", "institutional_decision_engine", True),
        ("Trade Lifecycle", "21", "trade_lifecycle", True),
        ("Institutional Learning", "22", "institutional_learning", False),
        ("Replay Laboratory", "23", "replay_laboratory", False),
        ("Policy Governance", "24", "policy_governance", False),
        ("Shadow Validation", "25", "shadow_validation", False),
    ]
    engines = [_engine_row(name, phase, as_mapping(ctx.get(key)), expected_live=live) for name, phase, key, live in specs]
    performance = build_performance_scorecards(records)
    drift = build_drift_detection(records)
    health_average = mean([e["health_score"] for e in engines]) if engines else 0.0
    available_pct = sum(1 for e in engines if e["available"]) / len(engines) * 100.0 if engines else 0.0
    calibration = performance.get("calibration_error_points")
    calibration_score = 75.0 if calibration is None else _clamp(100.0 - calibration)
    learning_score = _clamp(40.0 + min(60.0, performance.get("sample_size", 0) * 2.0))
    shadow = as_mapping(ctx.get("shadow_validation"))
    shadow_score = 80.0 if shadow.get("promotion_candidate_count") else 65.0 if shadow.get("trial_count") else 50.0
    sci = _clamp(0.40 * health_average + 0.20 * available_pct + 0.15 * calibration_score + 0.15 * learning_score + 0.10 * shadow_score)
    rankings = sorted(engines, key=lambda e: e["health_score"], reverse=True)
    overall_state = "CRITICAL" if any(e["status"] == "RED" for e in engines[:11]) else "DEGRADED" if any(e["status"] == "YELLOW" for e in engines) else "HEALTHY"
    if drift["state"] == "DRIFT_DETECTED":
        overall_state = "DEGRADED" if overall_state == "HEALTHY" else overall_state
    return {
        "version": "PHASE_26",
        "as_of": utc_now_iso(),
        "mode": "INSTITUTIONAL_PERFORMANCE_COMMAND_CENTER",
        "system_state": overall_state,
        "system_confidence_index": {"score": round(sci, 1), "status": _status(sci), "components": {
            "engine_health": round(health_average, 1), "availability": round(available_pct, 1),
            "calibration": round(calibration_score, 1), "learning_maturity": round(learning_score, 1),
            "shadow_validation": round(shadow_score, 1)}},
        "system_health": {"average_score": round(health_average, 1), "green": sum(e["status"] == "GREEN" for e in engines),
                          "yellow": sum(e["status"] == "YELLOW" for e in engines), "red": sum(e["status"] == "RED" for e in engines),
                          "engines": engines},
        "performance_scorecard": performance,
        "drift_detection": drift,
        "engine_rankings": rankings,
        "policy_pipeline": {"proposals": len(as_mapping(ctx.get("policy_governance")).get("proposals") or []),
                            "shadow_trials": int(shadow.get("trial_count") or 0),
                            "promotion_candidates": int(shadow.get("promotion_candidate_count") or 0)},
        "controls": {"observational_only": True, "live_configuration_mutation": False, "risk_mutation": False,
                     "authorization_override": False, "lifecycle_override": False, "automatic_policy_promotion": False,
                     "broker_access": False, "order_submission": False},
        "safety_note": "Phase 26 is an observational executive layer. Scores and drift alerts cannot alter trades, policies, risk, authorization, lifecycle management, or broker orders.",
    }
