"""APEX Trade Director Phase 23 — Institutional Replay & Decision Laboratory.

Reconstructs archived Phase 22 trade cases from information stored at decision time,
creates a chronological decision timeline, performs bounded counterfactual analysis,
and produces advisory decision-quality audits. No live provider or broker calls occur.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

from engine.trade_director_institutional_learning import (
    get_learning_record,
    learning_history,
)
from engine.trade_director_lifecycle_contracts import as_mapping, utc_now_iso


def _f(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _u(value: Any) -> str:
    return str(value or "").strip().upper()


def _iso(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _event(ts: str, engine: str, event: str, value: Any, detail: str = "") -> Dict[str, Any]:
    return {"timestamp": ts, "engine": engine, "event": event, "value": value, "detail": detail}


def _timeline(record: Mapping[str, Any]) -> List[Dict[str, Any]]:
    entered = _iso(record.get("entered_at"), record.get("closed_at") or utc_now_iso())
    closed = _iso(record.get("closed_at"), entered)
    market = as_mapping(record.get("market_context"))
    decision = as_mapping(record.get("decision_context"))
    execution = as_mapping(record.get("execution_context"))
    governed = as_mapping(decision.get("governed_decision"))
    strategy = as_mapping(decision.get("strategy"))
    contract = as_mapping(decision.get("contract"))
    lifecycle = as_mapping(execution.get("trade_lifecycle"))
    events: List[Dict[str, Any]] = []

    session = as_mapping(market.get("session"))
    memory = as_mapping(market.get("market_memory"))
    cross = as_mapping(market.get("cross_asset"))
    mtf = as_mapping(market.get("multi_timeframe"))
    flow = as_mapping(market.get("institutional_flow"))
    events.extend([
        _event(entered, "PHASE_11", "SESSION_CONTEXT", session.get("decision_gate") or as_mapping(session.get("session")).get("mode") or "UNKNOWN"),
        _event(entered, "PHASE_12", "MARKET_MEMORY", memory.get("regime") or memory.get("market_regime") or "UNKNOWN"),
        _event(entered, "PHASE_13", "CROSS_ASSET", cross.get("dominant_direction") or cross.get("bias") or "UNKNOWN"),
        _event(entered, "PHASE_14", "STRATEGY_SELECTED", strategy.get("selected_strategy") or strategy.get("strategy") or record.get("strategy") or "UNKNOWN"),
        _event(entered, "PHASE_15", "CONTRACT_SELECTED", as_mapping(contract.get("best_contract") or contract.get("selected_contract")).get("symbol") or record.get("contract_symbol") or "UNKNOWN"),
        _event(entered, "PHASE_17", "TIMEFRAME_GATE", mtf.get("decision_gate") or "UNKNOWN"),
        _event(entered, "PHASE_18", "FLOW_GATE", flow.get("decision_gate") or "UNKNOWN"),
        _event(entered, "PHASE_20", "AUTHORIZATION", governed.get("decision_gate") or governed.get("authorization") or "ARCHIVED", f"Confidence {record.get('decision_confidence') or 0}"),
    ])
    for item in record.get("engine_evidence") or []:
        item = as_mapping(item)
        events.append(_event(str(item.get("timestamp") or entered), str(item.get("engine") or "EVIDENCE"), "EVIDENCE", item.get("value"), str(item.get("detail") or "")))
    events.append(_event(entered, "PHASE_21", "LIFECYCLE", lifecycle.get("lifecycle_state") or lifecycle.get("state") or "POSITION_ACTIVE"))
    events.append(_event(closed, "PHASE_22", "OUTCOME_ARCHIVED", "WIN" if record.get("win") else "LOSS", f"{record.get('r_multiple')}R"))
    return sorted(events, key=lambda e: (e["timestamp"], e["engine"], e["event"]))


def _scorecard(record: Mapping[str, Any]) -> Dict[str, Any]:
    learning = as_mapping(record.get("learning_context"))
    outcome = as_mapping(record.get("outcome_context"))
    pnl = _f(record.get("realized_pnl"), 0.0) or 0.0
    r = _f(record.get("r_multiple"), 0.0) or 0.0
    mfe = _f(record.get("mfe"), None)
    mae = _f(record.get("mae"), None)
    confidence = _f(record.get("decision_confidence"), 0.0) or 0.0
    direction = 85 if learning.get("direction_correct", pnl > 0) else 25
    context = max(20, min(100, 45 + confidence * 0.5))
    strategy = max(10, min(100, 55 + r * 15))
    entry = {"EARLY": 55, "LATE": 55, "OPTIMAL": 95, "GOOD": 82}.get(_u(learning.get("entry_timing")), 70)
    exit_score = _f(learning.get("exit_efficiency_pct"), None)
    exit_quality = max(0, min(100, exit_score if exit_score is not None else 72 + r * 8))
    risk = 75.0
    if mae is not None and mfe is not None and abs(mae) + abs(mfe) > 0:
        risk = max(10, min(100, 50 + (abs(mfe) - abs(mae)) / (abs(mfe) + abs(mae)) * 50))
    lifecycle = _f(learning.get("decision_quality_score"), 65.0) or 65.0
    components = {
        "context_quality": round(context, 1), "direction_quality": round(direction, 1),
        "strategy_selection": round(strategy, 1), "entry_timing": round(entry, 1),
        "risk_management": round(risk, 1), "exit_quality": round(exit_quality, 1),
        "lifecycle_management": round(lifecycle, 1),
    }
    overall = round(sum(components.values()) / len(components), 1)
    return {**components, "overall_institutional_score": overall, "grade": "A" if overall >= 90 else "B" if overall >= 80 else "C" if overall >= 70 else "D" if overall >= 60 else "F", "source": outcome.get("source") or "ARCHIVED_OUTCOME"}


def _counterfactuals(record: Mapping[str, Any]) -> List[Dict[str, Any]]:
    r = _f(record.get("r_multiple"), 0.0) or 0.0
    mfe = _f(record.get("mfe"), None)
    mae = _f(record.get("mae"), None)
    duration = _f(record.get("duration_minutes"), 0.0) or 0.0
    scenarios = [{"scenario": "ACTUAL", "estimated_r": round(r, 2), "confidence": "OBSERVED", "basis": "Archived confirmed outcome"}]
    if mfe is not None:
        scenarios.append({"scenario": "HOLD_TO_MFE", "estimated_r": round(mfe, 2), "confidence": "BOUND", "basis": "Upper bound from archived maximum favorable excursion; not assumed executable"})
    if r > 0:
        scenarios.append({"scenario": "TP1_PARTIAL_THEN_RUNNER", "estimated_r": round(min((mfe if mfe is not None else r) * 0.75, r + 0.5), 2), "confidence": "HEURISTIC", "basis": "Bounded partial-profit simulation"})
    if mae is not None:
        scenarios.append({"scenario": "EARLIER_DEFENSIVE_EXIT", "estimated_r": round(max(mae, min(r, -0.25)), 2), "confidence": "HEURISTIC", "basis": "Uses archived adverse excursion only; no tick-level fill claim"})
    scenarios.append({"scenario": "ONE_CONFIRMATION_LATER", "estimated_r": round(r - 0.15 if r > 0 else r + 0.1, 2), "confidence": "HEURISTIC", "basis": f"Timing sensitivity estimate for a {duration:.1f}-minute trade"})
    return scenarios


def _strategy_comparison(record: Mapping[str, Any]) -> List[Dict[str, Any]]:
    actual = _u(record.get("strategy") or "UNCLASSIFIED")
    r = _f(record.get("r_multiple"), 0.0) or 0.0
    direction = _u(record.get("direction"))
    candidates = [actual, "LONG_OPTION", "DEBIT_SPREAD", "CREDIT_SPREAD", "IRON_CONDOR"]
    seen = set(); rows = []
    for name in candidates:
        if not name or name in seen: continue
        seen.add(name)
        if name == actual:
            est, basis = r, "Observed strategy outcome"
        elif name == "DEBIT_SPREAD":
            est, basis = r * 0.75, "Capped directional proxy"
        elif name == "LONG_OPTION":
            est, basis = r * 1.05, "Directional convexity proxy"
        elif name == "CREDIT_SPREAD":
            est, basis = (0.55 if r > 0 else -0.75), "Defined-risk premium proxy"
        else:
            est, basis = (-0.4 if abs(r) > 0.8 else 0.35), "Range-strategy proxy"
        rows.append({"strategy": name, "estimated_r": round(est, 2), "direction": direction, "basis": basis, "simulation_only": name != actual})
    return sorted(rows, key=lambda x: x["estimated_r"], reverse=True)


def _lessons(record: Mapping[str, Any], scorecard: Mapping[str, Any], counterfactuals: Sequence[Mapping[str, Any]]) -> List[str]:
    learning = as_mapping(record.get("learning_context")); lessons = []
    lessons.extend(str(x) for x in learning.get("what_worked") or [] if str(x).strip())
    lessons.extend(str(x) for x in learning.get("what_failed") or [] if str(x).strip())
    lessons.extend(str(x) for x in learning.get("improvement") or [] if str(x).strip())
    if scorecard.get("entry_timing", 100) < 70: lessons.append("Review entry timing against the last pre-entry confirmation snapshot.")
    if scorecard.get("exit_quality", 100) < 70: lessons.append("Compare the actual exit with the bounded MFE and partial-runner scenarios.")
    if not lessons: lessons.append("Maintain the original evidence chain and collect more comparable cases before changing policy.")
    return lessons[:8]


def build_replay_case(trade_id: Optional[str] = None, record: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    archived = dict(record or (get_learning_record(str(trade_id)) if trade_id else {}) or {})
    if not archived:
        return {"version": "PHASE_23", "ok": False, "state": "NO_ARCHIVED_CASE", "trade_id": trade_id, "message": "A Phase 22 archived trade is required for replay."}
    scorecard = _scorecard(archived)
    counterfactuals = _counterfactuals(archived)
    replay_id = "R23-" + hashlib.sha256(str(archived.get("trade_id")).encode()).hexdigest()[:16].upper()
    return {
        "version": "PHASE_23", "ok": True, "mode": "OFFLINE_DECISION_REPLAY",
        "replay_id": replay_id, "trade_id": archived.get("trade_id"), "symbol": archived.get("symbol"),
        "strategy": archived.get("strategy"), "direction": archived.get("direction"),
        "entered_at": archived.get("entered_at"), "closed_at": archived.get("closed_at"),
        "actual_outcome": {"realized_pnl": archived.get("realized_pnl"), "r_multiple": archived.get("r_multiple"), "mfe": archived.get("mfe"), "mae": archived.get("mae"), "win": archived.get("win")},
        "decision_timeline": _timeline(archived), "decision_scorecard": scorecard,
        "counterfactuals": counterfactuals, "strategy_comparison": _strategy_comparison(archived),
        "lessons_learned": _lessons(archived, scorecard, counterfactuals),
        "lookahead_policy": {"future_data_used_in_reconstruction": False, "observed_outcome_used_only_for_post_trade_audit": True, "counterfactuals_are_simulations": True},
        "safety_note": "Phase 23 is offline and advisory. It cannot place orders, modify Phase 20/21 decisions, rewrite Phase 22 outcomes, or represent heuristic counterfactuals as executable fills.",
    }


def replay_library(limit: int = 100) -> List[Dict[str, Any]]:
    rows = learning_history(limit)
    return [{"trade_id": r.get("trade_id"), "symbol": r.get("symbol"), "strategy": r.get("strategy"), "direction": r.get("direction"), "closed_at": r.get("closed_at"), "win": r.get("win"), "r_multiple": r.get("r_multiple"), "decision_quality": as_mapping(r.get("learning_context")).get("decision_quality_score")} for r in rows]


def build_replay_lab(trade_id: Optional[str] = None, *, limit: int = 100) -> Dict[str, Any]:
    library = replay_library(limit)
    selected = trade_id or (library[0]["trade_id"] if library else None)
    case = build_replay_case(selected) if selected else build_replay_case()
    return {"version": "PHASE_23", "as_of": utc_now_iso(), "mode": "INSTITUTIONAL_REPLAY_LAB", "selected_trade_id": selected, "replay_case": case, "replay_library": library, "case_count": len(library), "read_only": True, "safety_note": "Replay is reconstructed from the Phase 22 ledger and remains read-only."}
