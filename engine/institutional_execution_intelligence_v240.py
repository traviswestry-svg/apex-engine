"""APEX 24.0 Institutional Execution Intelligence.

Advisory-only lifecycle orchestration from approved idea through entry,
management, exit, journal, and replay. No broker mutation is permitted here.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

from .institutional_ai_trading_coach_v235 import build_trading_coach
from .institutional_forecast_engine_v232 import build_institutional_forecast
from .institutional_playbook_engine_v233 import build_institutional_playbooks
from .institutional_trading_brain_v230 import build_institutional_trading_brain

VERSION = "17.0.0_INSTITUTIONAL_EXECUTION_INTELLIGENCE"
SEMANTIC_VERSION = "17.0.0"
SCHEMA_VERSION = "apex.institutional_execution_intelligence.v1"
_ALLOWED_STATES = ("IDEA", "APPROVED", "ENTERED", "MANAGING", "PROTECTED", "EXITED", "CANCELLED")
_TRANSITIONS = {
    "IDEA": {"APPROVED", "CANCELLED"},
    "APPROVED": {"ENTERED", "CANCELLED"},
    "ENTERED": {"MANAGING", "PROTECTED", "EXITED"},
    "MANAGING": {"PROTECTED", "EXITED"},
    "PROTECTED": {"MANAGING", "EXITED"},
    "EXITED": set(),
    "CANCELLED": set(),
}


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
        CREATE TABLE IF NOT EXISTS apex_execution_lifecycles_v240(
          lifecycle_id TEXT PRIMARY KEY,
          ticker TEXT NOT NULL,
          state TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          playbook_id TEXT,
          strategy_family TEXT,
          entry_price REAL,
          stop_price REAL,
          breakeven_price REAL,
          tp1 REAL,
          tp2 REAL,
          tp3 REAL,
          quantity REAL,
          realized_r REAL,
          metadata_json TEXT NOT NULL,
          integrity_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS apex_execution_events_v240(
          event_id TEXT PRIMARY KEY,
          lifecycle_id TEXT NOT NULL,
          sequence_no INTEGER NOT NULL,
          event_type TEXT NOT NULL,
          from_state TEXT,
          to_state TEXT,
          created_at TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          integrity_hash TEXT NOT NULL,
          UNIQUE(lifecycle_id, sequence_no)
        );
        CREATE INDEX IF NOT EXISTS idx_exec_v240_lifecycle ON apex_execution_events_v240(lifecycle_id, sequence_no);
        """)


def _f(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _clamp(v: Any, low: float = 0.0, high: float = 100.0) -> float:
    try:
        return max(low, min(high, float(v)))
    except (TypeError, ValueError):
        return low


def _levels(payload: Mapping[str, Any]) -> Dict[str, Optional[float]]:
    entry = _f(payload.get("entry_price"))
    stop = _f(payload.get("stop_price"))
    risk = abs(entry - stop) if entry is not None and stop is not None else None
    direction = str(payload.get("direction") or "CALL").upper()
    sign = -1.0 if direction in ("PUT", "BEAR", "SHORT") else 1.0
    return {
        "entry_price": entry,
        "stop_price": stop,
        "breakeven_price": _f(payload.get("breakeven_price")) if payload.get("breakeven_price") is not None else entry,
        "tp1": _f(payload.get("tp1")) if payload.get("tp1") is not None else (entry + sign * risk if entry is not None and risk is not None else None),
        "tp2": _f(payload.get("tp2")) if payload.get("tp2") is not None else (entry + sign * risk * 1.5 if entry is not None and risk is not None else None),
        "tp3": _f(payload.get("tp3")) if payload.get("tp3") is not None else (entry + sign * risk * 2.0 if entry is not None and risk is not None else None),
    }


def _execution_score(last: Dict[str, Any], trade: Mapping[str, Any]) -> Dict[str, Any]:
    brain = build_institutional_trading_brain(last)
    forecast = build_institutional_forecast(last)
    playbooks = build_institutional_playbooks(last)
    coach = build_trading_coach(last, phase="PRE_TRADE", trade=trade)
    score = 50.0
    reasons: list[str] = []
    if (brain.get("execution_readiness") or {}).get("eligible"):
        score += 15; reasons.append("TRADING_BRAIN_READY")
    else:
        score -= 20; reasons.append("TRADING_BRAIN_BLOCKED")
    if forecast.get("status") == "ACTIVE":
        score += 10; reasons.append("FORECAST_ACTIVE")
    else:
        score -= 10; reasons.append("FORECAST_LIMITED")
    selected = playbooks.get("selected_playbook") or {}
    if (playbooks.get("execution_readiness") or {}).get("eligible"):
        score += 15; reasons.append("PLAYBOOK_READY")
    else:
        score -= 15; reasons.append("PLAYBOOK_NOT_READY")
    recommendation = (coach.get("coaching") or {}).get("recommendation")
    score += {"TAKE": 10, "REDUCE_SIZE": -5, "STAND_DOWN": -25}.get(str(recommendation), 0)
    if trade.get("chased"):
        score -= 20; reasons.append("CHASE_RISK")
    slippage_bps = _f(trade.get("estimated_slippage_bps")) or 0.0
    if slippage_bps > 15:
        score -= min(20, (slippage_bps - 15) / 2); reasons.append("ELEVATED_SLIPPAGE")
    score = round(_clamp(score), 1)
    return {
        "score": score,
        "grade": "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "F",
        "eligible": score >= 70 and recommendation != "STAND_DOWN",
        "reasons": reasons,
        "playbook_id": selected.get("playbook_id"),
        "strategy_family": selected.get("strategy_family"),
        "coach_recommendation": recommendation,
        "slippage": {"estimated_bps": slippage_bps, "risk": "HIGH" if slippage_bps > 25 else "ELEVATED" if slippage_bps > 15 else "NORMAL"},
        "entry_quality": "CHASED" if trade.get("chased") else "LATE" if trade.get("late_entry") else "ON_PLAN",
    }


def build_execution_intelligence(last: Dict[str, Any], trade: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    last = last if isinstance(last, dict) else {}
    trade = dict(trade or {})
    scoring = _execution_score(last, trade)
    levels = _levels(trade)
    management = {
        "tp1_action": "TAKE_PARTIAL_AND_EVALUATE_BREAKEVEN",
        "tp2_action": "LOCK_PROFIT_AND_REDUCE_REMAINDER",
        "tp3_action": "EXIT_REMAINDER_UNLESS_PLAYBOOK_EXPLICITLY_EXTENDS",
        "breakeven_eligible_after": "TP1_OR_STRUCTURE_CONFIRMATION",
        "stop_adjustment": "ADVISORY_ONLY",
        "max_hold_minutes": int(trade.get("max_hold_minutes", 5) or 5),
    }
    return {
        "ok": True, "version": VERSION, "semantic_version": SEMANTIC_VERSION, "schema_version": SCHEMA_VERSION,
        "evaluated_at": _now(), "ticker": str(last.get("ticker") or "SPX"),
        "execution_score": scoring, "levels": levels, "management_plan": management,
        "lifecycle_states": list(_ALLOWED_STATES),
        "guardrails": {"advisory_only": True, "broker_mutation": False, "automatic_execution": False, "automatic_order_change": False, "human_confirmation_required": True, "existing_kill_switch_authoritative": True},
    }


def create_lifecycle(last: Dict[str, Any], payload: Mapping[str, Any]) -> Dict[str, Any]:
    init_db()
    intelligence = build_execution_intelligence(last, payload)
    lifecycle_id = str(payload.get("lifecycle_id") or uuid.uuid4())
    now = _now(); levels = intelligence["levels"]; score = intelligence["execution_score"]
    state = "APPROVED" if bool(payload.get("human_confirmed")) and score["eligible"] else "IDEA"
    row = {
        "lifecycle_id": lifecycle_id, "ticker": intelligence["ticker"], "state": state, "created_at": now, "updated_at": now,
        "playbook_id": payload.get("playbook_id") or score.get("playbook_id"), "strategy_family": payload.get("strategy_family") or score.get("strategy_family"),
        **levels, "quantity": _f(payload.get("quantity")), "realized_r": None, "metadata": dict(payload.get("metadata") or {}),
    }
    row["integrity_hash"] = hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()
    with _conn() as conn:
        conn.execute("INSERT INTO apex_execution_lifecycles_v240 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            row["lifecycle_id"], row["ticker"], row["state"], row["created_at"], row["updated_at"], row["playbook_id"], row["strategy_family"],
            row["entry_price"], row["stop_price"], row["breakeven_price"], row["tp1"], row["tp2"], row["tp3"], row["quantity"], row["realized_r"], json.dumps(row["metadata"], sort_keys=True), row["integrity_hash"]))
        _insert_event(conn, lifecycle_id, "LIFECYCLE_CREATED", None, state, {"execution_score": score, "levels": levels})
    return {"ok": True, "status": "CREATED", "lifecycle_id": lifecycle_id, "state": state, "execution_intelligence": intelligence, "production_effect": "NONE"}


def _insert_event(conn: sqlite3.Connection, lifecycle_id: str, event_type: str, from_state: Optional[str], to_state: Optional[str], payload: Mapping[str, Any]) -> None:
    seq = int(conn.execute("SELECT COALESCE(MAX(sequence_no),0)+1 FROM apex_execution_events_v240 WHERE lifecycle_id=?", (lifecycle_id,)).fetchone()[0])
    body = dict(payload); digest = hashlib.sha256(json.dumps({"lifecycle_id": lifecycle_id, "sequence_no": seq, "event_type": event_type, "from_state": from_state, "to_state": to_state, "payload": body}, sort_keys=True, default=str).encode()).hexdigest()
    conn.execute("INSERT INTO apex_execution_events_v240 VALUES(?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), lifecycle_id, seq, event_type, from_state, to_state, _now(), json.dumps(body, sort_keys=True, default=str), digest))


def transition_lifecycle(lifecycle_id: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    init_db(); target = str(payload.get("to_state") or "").upper()
    if target not in _ALLOWED_STATES:
        return {"ok": False, "status": "REJECTED", "error": "INVALID_TARGET_STATE"}
    with _conn() as conn:
        row = conn.execute("SELECT * FROM apex_execution_lifecycles_v240 WHERE lifecycle_id=?", (lifecycle_id,)).fetchone()
        if not row: return {"ok": False, "status": "NOT_FOUND"}
        current = str(row["state"])
        if target not in _TRANSITIONS.get(current, set()):
            return {"ok": False, "status": "REJECTED", "error": "INVALID_STATE_TRANSITION", "from_state": current, "to_state": target}
        if target == "ENTERED" and not bool(payload.get("human_confirmed")):
            return {"ok": False, "status": "REJECTED", "error": "HUMAN_CONFIRMATION_REQUIRED"}
        now = _now(); realized_r = _f(payload.get("realized_r")) if target == "EXITED" else row["realized_r"]
        conn.execute("UPDATE apex_execution_lifecycles_v240 SET state=?,updated_at=?,realized_r=? WHERE lifecycle_id=?", (target, now, realized_r, lifecycle_id))
        _insert_event(conn, lifecycle_id, str(payload.get("event_type") or "STATE_TRANSITION"), current, target, payload)
    return {"ok": True, "status": "UPDATED", "lifecycle_id": lifecycle_id, "from_state": current, "to_state": target, "production_effect": "NONE"}


def replay_lifecycle(lifecycle_id: str) -> Dict[str, Any]:
    init_db()
    with _conn() as conn:
        lifecycle = conn.execute("SELECT * FROM apex_execution_lifecycles_v240 WHERE lifecycle_id=?", (lifecycle_id,)).fetchone()
        events = conn.execute("SELECT * FROM apex_execution_events_v240 WHERE lifecycle_id=? ORDER BY sequence_no", (lifecycle_id,)).fetchall()
    if not lifecycle: return {"ok": False, "status": "NOT_FOUND"}
    item = dict(lifecycle); item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
    timeline=[]
    for event in events:
        e=dict(event); e["payload"] = json.loads(e.pop("payload_json") or "{}"); timeline.append(e)
    return {"ok": True, "status": "REPLAY_READY", "lifecycle": item, "timeline": timeline, "event_count": len(timeline), "point_in_time_ordered": True, "production_effect": "NONE"}


def journal(ticker: str = "SPX", limit: int = 50) -> Dict[str, Any]:
    init_db(); limit=max(1,min(int(limit),200))
    with _conn() as conn:
        rows=[dict(r) for r in conn.execute("SELECT * FROM apex_execution_lifecycles_v240 WHERE ticker=? ORDER BY updated_at DESC LIMIT ?",(ticker,limit)).fetchall()]
    for row in rows: row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
    return {"ok": True, "ticker": ticker, "count": len(rows), "lifecycles": rows, "read_only": True}
