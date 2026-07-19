"""APEX 23.5 Institutional AI Trading Coach.

Advisory-only coaching across pre-trade, active-trade, and post-trade phases.
The coach never places orders, changes stops, mutates risk limits, or overrides
existing kill switches. Completed reviews may be persisted as sanitized records;
feeding a matured outcome to Continuous Learning requires an explicit request.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

from .continuous_learning_calibration_v234 import build_continuous_learning, record_outcome
from .institutional_forecast_engine_v232 import build_institutional_forecast
from .institutional_playbook_engine_v233 import build_institutional_playbooks
from .institutional_regime_intelligence_v231 import build_regime_intelligence
from .institutional_trading_brain_v230 import build_institutional_trading_brain

VERSION = "16.5.0_INSTITUTIONAL_AI_TRADING_COACH"
SEMANTIC_VERSION = "16.5.0"
SCHEMA_VERSION = "apex.institutional_ai_trading_coach.v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path() -> str:
    return os.getenv("DB_PATH", "apex_tracking.db")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS apex_coach_reviews_v235(
          review_id TEXT PRIMARY KEY,
          ticker TEXT NOT NULL,
          trade_id TEXT,
          phase TEXT NOT NULL,
          created_at TEXT NOT NULL,
          playbook_id TEXT,
          regime TEXT,
          forecast_scenario TEXT,
          recommendation TEXT NOT NULL,
          rule_adherence REAL NOT NULL,
          entry_discipline REAL NOT NULL,
          stop_discipline REAL NOT NULL,
          profit_management REAL NOT NULL,
          behavioral_flags_json TEXT NOT NULL,
          strengths_json TEXT NOT NULL,
          corrections_json TEXT NOT NULL,
          metadata_json TEXT NOT NULL,
          integrity_hash TEXT NOT NULL,
          UNIQUE(ticker, trade_id, phase)
        );
        CREATE INDEX IF NOT EXISTS idx_coach_v235_created ON apex_coach_reviews_v235(ticker, created_at);
        """)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return low


def _context(last: Dict[str, Any], history: Any = None, before: Optional[str] = None) -> Dict[str, Any]:
    brain = build_institutional_trading_brain(last, history, before=before)
    regime = build_regime_intelligence(last, history, before=before)
    forecast = build_institutional_forecast(last, history, before=before)
    playbooks = build_institutional_playbooks(last, history, before=before)
    learning = build_continuous_learning(last, history, before=before)
    return {"brain": brain, "regime": regime, "forecast": forecast, "playbooks": playbooks, "learning": learning}


def _pre_trade(ctx: Mapping[str, Any], trade: Mapping[str, Any]) -> Dict[str, Any]:
    brain = ctx["brain"]; regime = ctx["regime"]; forecast = ctx["forecast"]; playbooks = ctx["playbooks"]
    selected = playbooks.get("selected_playbook") or {}
    blockers: list[str] = []
    warnings: list[str] = []
    checks = {
        "playbook_selected": selected.get("playbook_id") not in (None, "WAIT_FOR_CONFIRMATION"),
        "playbook_execution_ready": bool((playbooks.get("execution_readiness") or {}).get("eligible")),
        "brain_execution_ready": bool((brain.get("execution_readiness") or {}).get("eligible")),
        "forecast_active": forecast.get("status") == "ACTIVE",
        "regime_confirmed": (regime.get("transition") or {}).get("state") in ("STABLE", "CONFIRMED"),
        "human_confirmation_present": bool(trade.get("human_confirmed", False)),
    }
    daily_loss = abs(float(trade.get("daily_loss", 0) or 0))
    max_daily_loss = abs(float(trade.get("max_daily_loss", os.getenv("TRADE_MAX_DAILY_LOSS", "1000")) or 1000))
    trades_today = int(trade.get("trades_today", 0) or 0)
    max_trades = int(trade.get("max_trades_per_day", os.getenv("TRADE_MAX_TRADES_PER_DAY", "3")) or 3)
    chased = bool(trade.get("chased", False))
    rr = float(trade.get("risk_reward", 0) or 0)
    if daily_loss >= max_daily_loss: blockers.append("DAILY_LOSS_LIMIT_REACHED")
    if trades_today >= max_trades: blockers.append("MAX_TRADES_REACHED")
    if not checks["playbook_execution_ready"]: blockers.append("PLAYBOOK_NOT_READY")
    if not checks["brain_execution_ready"]: blockers.append("TRADING_BRAIN_NOT_READY")
    if not checks["forecast_active"]: blockers.append("FORECAST_LIMITED")
    if not checks["human_confirmation_present"]: blockers.append("HUMAN_CONFIRMATION_REQUIRED")
    if chased: blockers.append("ENTRY_IS_CHASED")
    if rr and rr < 1.2: warnings.append("RISK_REWARD_BELOW_1_2")
    if not checks["regime_confirmed"]: warnings.append("REGIME_TRANSITION_UNCONFIRMED")
    conflicts = brain.get("conflicting_evidence") or []
    if any(str(x.get("severity", "")).upper() == "HIGH" for x in conflicts if isinstance(x, dict)):
        blockers.append("HIGH_SEVERITY_EVIDENCE_CONFLICT")
    recommendation = "STAND_DOWN" if blockers else "REDUCE_SIZE" if warnings else "TAKE"
    return {
        "phase": "PRE_TRADE", "recommendation": recommendation, "checks": checks,
        "blockers": sorted(set(blockers)), "warnings": sorted(set(warnings)),
        "selected_playbook": selected.get("playbook_id"), "strategy_family": selected.get("strategy_family"),
        "message": "Do not enter until every blocker is cleared." if blockers else "Setup is eligible for human-confirmed execution." if recommendation == "TAKE" else "Setup is viable but uncertainty warrants reduced exposure.",
    }


def _active_trade(ctx: Mapping[str, Any], trade: Mapping[str, Any]) -> Dict[str, Any]:
    brain = ctx["brain"]; forecast = ctx["forecast"]
    minutes = float(trade.get("minutes_in_trade", 0) or 0)
    max_hold = float(trade.get("max_hold_minutes", 5) or 5)
    tp1 = bool(trade.get("tp1_reached", False)); tp2 = bool(trade.get("tp2_reached", False))
    invalidated = bool(trade.get("structure_invalidated", False) or trade.get("forecast_invalidated", False))
    stop_hit = bool(trade.get("stop_hit", False)); adverse_add = bool(trade.get("adding_to_loser", False))
    brain_ready = bool((brain.get("execution_readiness") or {}).get("eligible"))
    actions: list[str] = []
    if adverse_add: actions.append("DO_NOT_ADD")
    if stop_hit or invalidated: recommendation = "EXIT"; actions.append("EXIT_NOW")
    elif minutes >= max_hold: recommendation = "EXIT"; actions.append("MAX_HOLD_REACHED")
    elif tp2: recommendation = "PROTECT"; actions.extend(["LOCK_PROFIT", "MANAGE_REMAINDER_TO_PLAYBOOK"])
    elif tp1: recommendation = "PROTECT"; actions.extend(["BREAKEVEN_ELIGIBLE", "PARTIAL_PROFIT_PER_PLAYBOOK"])
    elif not brain_ready or forecast.get("status") != "ACTIVE": recommendation = "REDUCE_RISK"; actions.append("THESIS_QUALITY_DEGRADED")
    else: recommendation = "HOLD"; actions.append("THESIS_REMAINS_VALID")
    return {
        "phase": "ACTIVE_TRADE", "recommendation": recommendation, "actions": actions,
        "minutes_in_trade": minutes, "max_hold_minutes": max_hold,
        "thesis_valid": not invalidated and brain_ready, "stop_respected": not stop_hit,
        "message": {
            "HOLD": "Hold only while the approved thesis and structure remain valid.",
            "PROTECT": "Protect realized progress according to the approved playbook.",
            "REDUCE_RISK": "Evidence quality has weakened; reduce exposure rather than hope.",
            "EXIT": "The trade has reached a hard lifecycle exit condition.",
        }[recommendation],
    }


def _post_trade(ctx: Mapping[str, Any], trade: Mapping[str, Any]) -> Dict[str, Any]:
    chased = bool(trade.get("chased", False)); stop_respected = bool(trade.get("stop_respected", True))
    exited_on_invalidation = bool(trade.get("exited_on_invalidation", False)); premature = bool(trade.get("premature_exit", False))
    overtraded = bool(trade.get("overtraded", False)); revenge = bool(trade.get("revenge_trade", False))
    held_beyond = bool(trade.get("held_beyond_invalidation", False)); followed_plan = bool(trade.get("followed_profit_plan", True))
    entry = 100 - (35 if chased else 0) - (20 if bool(trade.get("late_entry", False)) else 0)
    stop = 100 if stop_respected and not held_beyond else 35 if stop_respected else 0
    profit = 100 - (30 if premature else 0) - (35 if not followed_plan else 0)
    adherence = 100 - sum([30 if overtraded else 0, 35 if revenge else 0, 25 if held_beyond else 0, 20 if chased else 0])
    flags = [name for name, active in {
        "CHASING": chased, "PREMATURE_EXIT": premature, "OVERTRADING": overtraded,
        "REVENGE_TRADING": revenge, "HELD_BEYOND_INVALIDATION": held_beyond,
        "STOP_VIOLATION": not stop_respected,
    }.items() if active]
    strengths=[]; corrections=[]
    if stop_respected: strengths.append("STOP_DISCIPLINE")
    if exited_on_invalidation: strengths.append("STRUCTURE_BASED_EXIT")
    if followed_plan: strengths.append("PROFIT_PLAN_FOLLOWED")
    if chased: corrections.append("WAIT_FOR_APPROVED_ENTRY_LOCATION")
    if premature: corrections.append("USE_STRUCTURE_NOT_EMOTION_FOR_EXIT")
    if overtraded: corrections.append("HONOR_DAILY_TRADE_LIMIT")
    if revenge: corrections.append("ACTIVATE_COOLDOWN_AFTER_LOSS")
    if held_beyond: corrections.append("EXIT_WHEN_INVALIDATION_CONFIRMS")
    overall = round((_clamp(adherence)+_clamp(entry)+_clamp(stop)+_clamp(profit))/4, 1)
    grade = "A" if overall >= 90 else "B" if overall >= 80 else "C" if overall >= 70 else "D" if overall >= 60 else "F"
    return {
        "phase": "POST_TRADE", "recommendation": "REVIEW_COMPLETE", "behavioral_grade": grade,
        "overall_discipline_score": overall,
        "scorecard": {"rule_adherence": _clamp(adherence), "entry_discipline": _clamp(entry), "stop_discipline": _clamp(stop), "profit_management": _clamp(profit)},
        "behavioral_flags": flags, "strengths": strengths, "corrections": corrections,
        "strategy_quality_separate_from_execution_quality": True,
    }


def build_trading_coach(last: Dict[str, Any], history: Any = None, *, phase: str = "PRE_TRADE", trade: Optional[Mapping[str, Any]] = None, before: Optional[str] = None) -> Dict[str, Any]:
    last = last if isinstance(last, dict) else {}; trade = dict(trade or {})
    ctx = _context(last, history, before); phase = str(phase or "PRE_TRADE").upper()
    if phase == "ACTIVE_TRADE": coaching = _active_trade(ctx, trade)
    elif phase == "POST_TRADE": coaching = _post_trade(ctx, trade)
    else: phase = "PRE_TRADE"; coaching = _pre_trade(ctx, trade)
    selected = (ctx["playbooks"].get("selected_playbook") or {})
    return {
        "ok": True, "version": VERSION, "semantic_version": SEMANTIC_VERSION, "schema_version": SCHEMA_VERSION,
        "evaluated_at": _now(), "ticker": str(last.get("ticker") or "SPX"), "phase": phase,
        "coaching": coaching,
        "context": {"playbook": selected.get("playbook_id"), "regime": ctx["regime"].get("primary_regime"), "forecast": ctx["forecast"].get("primary_scenario"), "brain_confidence": ctx["brain"].get("calibrated_confidence"), "learning_state": ctx["learning"].get("status")},
        "guardrails": {"advisory_only": True, "broker_mutation": False, "automatic_execution": False, "automatic_stop_change": False, "automatic_risk_change": False, "human_confirmation_required": True, "existing_kill_switch_authoritative": True, "look_ahead_protected": bool(before)},
    }


def record_review(payload: Mapping[str, Any]) -> Dict[str, Any]:
    init_db()
    phase = str(payload.get("phase") or "POST_TRADE").upper()
    if phase != "POST_TRADE":
        return {"ok": False, "status": "REJECTED", "error": "ONLY_POST_TRADE_REVIEWS_MAY_BE_RECORDED"}
    result = build_trading_coach(dict(payload.get("last") or {"ticker": payload.get("ticker", "SPX")}), phase=phase, trade=payload)
    coaching = result["coaching"]; scores = coaching["scorecard"]
    row = {
        "review_id": str(uuid.uuid4()), "ticker": result["ticker"], "trade_id": payload.get("trade_id"),
        "phase": phase, "created_at": _now(), "playbook_id": payload.get("playbook_id") or result["context"].get("playbook"),
        "regime": payload.get("regime") or result["context"].get("regime"), "forecast_scenario": payload.get("forecast_scenario") or result["context"].get("forecast"),
        "recommendation": coaching["recommendation"], "rule_adherence": scores["rule_adherence"], "entry_discipline": scores["entry_discipline"],
        "stop_discipline": scores["stop_discipline"], "profit_management": scores["profit_management"],
        "behavioral_flags": coaching["behavioral_flags"], "strengths": coaching["strengths"], "corrections": coaching["corrections"],
        "metadata": dict(payload.get("metadata") or {}),
    }
    row["integrity_hash"] = hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()
    try:
        with _conn() as conn:
            conn.execute("INSERT INTO apex_coach_reviews_v235 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                row["review_id"], row["ticker"], row["trade_id"], row["phase"], row["created_at"], row["playbook_id"], row["regime"], row["forecast_scenario"], row["recommendation"],
                row["rule_adherence"], row["entry_discipline"], row["stop_discipline"], row["profit_management"], json.dumps(row["behavioral_flags"]), json.dumps(row["strengths"]), json.dumps(row["corrections"]), json.dumps(row["metadata"], sort_keys=True), row["integrity_hash"],
            ))
    except sqlite3.IntegrityError:
        return {"ok": True, "status": "IMMUTABLE_EXISTS", "production_effect": "NONE"}
    learning = None
    if bool(payload.get("feed_continuous_learning", False)):
        matured = dict(payload.get("matured_outcome") or {})
        if matured:
            learning = record_outcome(matured)
    return {"ok": True, "status": "RECORDED", "review_id": row["review_id"], "integrity_hash": row["integrity_hash"], "learning_result": learning, "production_effect": "NONE"}


def behavioral_scorecard(ticker: str = "SPX") -> Dict[str, Any]:
    init_db()
    with _conn() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM apex_coach_reviews_v235 WHERE ticker=? ORDER BY created_at", (ticker,)).fetchall()]
    if not rows:
        return {"ok": True, "ticker": ticker, "status": "DORMANT", "samples": 0, "averages": {}, "behavioral_flags": {}}
    keys = ("rule_adherence", "entry_discipline", "stop_discipline", "profit_management")
    averages = {k: round(sum(float(r[k]) for r in rows)/len(rows), 2) for k in keys}
    flags: Dict[str, int] = {}
    for row in rows:
        for flag in json.loads(row["behavioral_flags_json"] or "[]"):
            flags[flag] = flags.get(flag, 0) + 1
    return {"ok": True, "ticker": ticker, "status": "ACTIVE" if len(rows) >= 10 else "PROVISIONAL", "samples": len(rows), "averages": averages, "behavioral_flags": dict(sorted(flags.items(), key=lambda x: (-x[1], x[0])))}
