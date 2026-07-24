"""APEX Trade Director Phase 37 — Mobile Momentum Intelligence.

Advisory-only Telegram/mobile alert state machine. It consumes governed Phase 35/36
outputs, suppresses duplicates, records every delivery attempt, and never transmits
broker orders.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

DB_PATH = Path(os.getenv("APEX_MOBILE_ALERT_DB", "apex_mobile_alerts.db"))
DEFAULT_COOLDOWN_SECONDS = int(os.getenv("APEX_MOMENTUM_ALERT_COOLDOWN_SECONDS", "300"))
ASSISTANT_URL = os.getenv("APEX_ASSISTANT_URL", "/assistant")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS mobile_alert_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TEXT NOT NULL,
          fingerprint TEXT NOT NULL,
          opportunity_key TEXT NOT NULL,
          stage TEXT NOT NULL,
          direction TEXT,
          trade_function TEXT,
          entry_quality REAL,
          confidence REAL,
          delivered INTEGER NOT NULL,
          delivery_channel TEXT NOT NULL,
          message TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_mobile_alert_opportunity
          ON mobile_alert_events(opportunity_key, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_mobile_alert_fingerprint
          ON mobile_alert_events(fingerprint, created_at DESC);
        """
    )
    return con


def _grade_score(grade: str) -> float:
    return {"A+": 96, "A": 87, "B+": 78, "B": 69}.get(str(grade or "").upper(), 0)


def _stage_rank(stage: str) -> int:
    return {
        "NONE": 0,
        "MOMENTUM_WATCH": 1,
        "MOMENTUM_PRIMED": 2,
        "ENTRY_WINDOW_OPEN": 3,
        "OPPORTUNITY_EXPIRED": 4,
        "SETUP_INVALIDATED": 4,
        "TAKE_PROFIT": 5,
        "EXIT_NOW": 5,
    }.get(stage, 0)


def classify_alert_stage(snapshot: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    s = dict(snapshot or {})
    lifecycle = dict(s.get("momentum_lifecycle") or {})
    router = dict(s.get("trade_function_router") or {})
    selected = dict(router.get("selected_function") or s.get("selected_function") or {})
    eq = dict(s.get("entry_quality") or lifecycle.get("entry_quality") or {})

    function = str(selected.get("function") or lifecycle.get("trade_function") or s.get("trade_function") or "").upper()
    direction = str(s.get("direction") or s.get("bias") or "NEUTRAL").upper()
    entry_score = _num(eq.get("entry_quality_score"), _grade_score(eq.get("entry_quality_grade")))
    confidence = _num(s.get("institutional_confidence", s.get("confidence", s.get("ici", 0))))
    trigger = str(s.get("trigger_state") or s.get("entry_trigger_state") or "WAITING").upper()
    market_open = bool(s.get("market_open", True))
    data_fresh = bool(s.get("data_fresh", True))
    risk_eligible = bool(s.get("risk_eligible", True))
    spread_ok = bool(s.get("spread_ok", True))
    invalidated = bool(s.get("invalidated", False))
    dq = dict(s.get("decision_quality") or {})
    dq_alert = dict(dq.get("alert_quality") or {})
    decision_quality_eligible = dq_alert.get("alert_eligible")

    rec = str(lifecycle.get("recommendation") or "").upper()
    if rec == "TAKE_PROFIT":
        stage = "TAKE_PROFIT"
    elif rec == "EXIT_NOW":
        stage = "EXIT_NOW"
    elif invalidated:
        stage = "SETUP_INVALIDATED"
    elif not market_open or not data_fresh:
        stage = "NONE"
    elif decision_quality_eligible is False:
        stage = "NONE"
    elif function != "MOMENTUM_BURST":
        stage = "NONE"
    elif trigger in {"CONFIRMED", "OPEN", "FIRED", "ENTRY_WINDOW_OPEN"} and entry_score >= 82 and confidence >= 75 and risk_eligible and spread_ok:
        stage = "ENTRY_WINDOW_OPEN"
    elif entry_score >= 90 and confidence >= 80 and risk_eligible and spread_ok:
        stage = "MOMENTUM_PRIMED"
    elif entry_score >= 74 and confidence >= 70 and risk_eligible:
        stage = "MOMENTUM_WATCH"
    else:
        stage = "NONE"

    return {
        "stage": stage,
        "stage_rank": _stage_rank(stage),
        "direction": direction,
        "trade_function": function or "UNSELECTED",
        "entry_quality_score": entry_score or None,
        "entry_quality_grade": eq.get("entry_quality_grade") or "UNRATED",
        "confidence": confidence or None,
        "trigger_state": trigger,
        "market_open": market_open,
        "data_fresh": data_fresh,
        "risk_eligible": risk_eligible,
        "spread_ok": spread_ok,
        "decision_quality_eligible": decision_quality_eligible,
        "decision_quality_blockers": dq_alert.get("blocking_conditions") or [],
        "reason": (
            "Phase 38 decision-quality policy suppressed this alert: "
            + ", ".join(dq_alert.get("blocking_conditions") or [])
            if stage == "NONE" and decision_quality_eligible is False
            else _reason(stage, entry_score, confidence, trigger)
        ),
    }


def _reason(stage: str, entry: float, confidence: float, trigger: str) -> str:
    reasons = {
        "MOMENTUM_WATCH": "Momentum Burst evidence is developing, but the entry trigger is not yet confirmed.",
        "MOMENTUM_PRIMED": "Entry quality and institutional confidence meet the governed primed thresholds.",
        "ENTRY_WINDOW_OPEN": "The governed entry trigger is confirmed while momentum conditions remain eligible.",
        "SETUP_INVALIDATED": "The prior momentum opportunity no longer satisfies its entry thesis.",
        "TAKE_PROFIT": "The Phase 36 premium-expansion objective has been reached.",
        "EXIT_NOW": "The Phase 36 adverse-premium threshold has been breached.",
        "NONE": "No mobile Momentum Burst alert is currently eligible.",
    }
    return reasons.get(stage, f"Entry {entry:.0f}; confidence {confidence:.0f}; trigger {trigger}.")


def opportunity_key(snapshot: Mapping[str, Any], state: Mapping[str, Any]) -> str:
    level = snapshot.get("trigger_level") or snapshot.get("entry_level") or snapshot.get("key_level") or "NA"
    session = snapshot.get("session_date") or _now().date().isoformat()
    return f"{session}|SPX|{state.get('direction')}|{state.get('trade_function')}|{level}"


def fingerprint(opportunity: str, stage: str) -> str:
    return hashlib.sha256(f"{opportunity}|{stage}".encode("utf-8")).hexdigest()


def format_alert(snapshot: Mapping[str, Any], state: Mapping[str, Any]) -> str:
    stage = state["stage"]
    icon = {
        "MOMENTUM_WATCH": "🟡", "MOMENTUM_PRIMED": "🟢", "ENTRY_WINDOW_OPEN": "🔵",
        "TAKE_PROFIT": "💰", "EXIT_NOW": "🚨", "SETUP_INVALIDATED": "🔴",
        "OPPORTUNITY_EXPIRED": "⚪",
    }.get(stage, "ℹ️")
    label = stage.replace("_", " ")
    lines = [f"{icon} APEX {label}", "", f"SPX {state.get('direction', 'NEUTRAL')}",
             f"Function: {state.get('trade_function')}"]
    if state.get("entry_quality_score") is not None:
        lines.append(f"Entry Quality: {state.get('entry_quality_grade')} / {state.get('entry_quality_score'):.0f}")
    if state.get("confidence") is not None:
        lines.append(f"Institutional Confidence: {state.get('confidence'):.0f}")
    if snapshot.get("suggested_contracts") is not None:
        lines.append(f"Suggested Size: {snapshot.get('suggested_contracts')} contract(s)")
    if snapshot.get("trigger_level") is not None:
        lines.append(f"Trigger: {snapshot.get('trigger_level')}")
    lifecycle = snapshot.get("momentum_lifecycle") or {}
    if stage in {"TAKE_PROFIT", "EXIT_NOW"}:
        lines.append(f"Premium Change: {lifecycle.get('premium_change')}")
        lines.append(f"Recommendation: {stage.replace('_', ' ')}")
    else:
        lines.append(f"Trigger State: {state.get('trigger_state')}")
        lines.append("Premium plan: +$2.00 objective / governed -$2.00 to -$3.00 protection")
    lines.extend(["", state.get("reason", ""), f"Open APEX: {snapshot.get('assistant_url') or ASSISTANT_URL}",
                  "Manual execution and confirmation required."])
    return "\n".join(str(x) for x in lines if x is not None)


def _last_event(opportunity: str) -> Optional[Dict[str, Any]]:
    with _connect() as con:
        row = con.execute("SELECT * FROM mobile_alert_events WHERE opportunity_key=? ORDER BY id DESC LIMIT 1", (opportunity,)).fetchone()
    return dict(row) if row else None


def dispatch_mobile_alert(snapshot: Optional[Mapping[str, Any]], sender: Callable[[str], bool], *,
                          force: bool = False, cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
                          now: Optional[datetime] = None) -> Dict[str, Any]:
    s = dict(snapshot or {})
    state = classify_alert_stage(s)
    stage = state["stage"]
    if stage == "NONE":
        return {"ok": True, "sent": False, "suppressed": True, "reason": state["reason"], "state": state}

    opp = opportunity_key(s, state)
    fp = fingerprint(opp, stage)
    last = _last_event(opp)
    current = now or _now()
    if not force and last:
        last_at = datetime.fromisoformat(last["created_at"])
        same_stage = last["stage"] == stage
        within = current - last_at < timedelta(seconds=max(0, cooldown_seconds))
        downgrade = _stage_rank(stage) < _stage_rank(last["stage"]) and stage not in {"SETUP_INVALIDATED", "EXIT_NOW"}
        if same_stage or within or downgrade:
            return {"ok": True, "sent": False, "suppressed": True,
                    "reason": "Duplicate/cooldown/state-regression suppression.", "state": state,
                    "last_stage": last["stage"]}

    message = format_alert(s, state)
    error = None
    delivered = False
    try:
        delivered = bool(sender(message))
        if not delivered:
            error = "Telegram sender returned false."
    except Exception as exc:  # defensive boundary
        error = str(exc)
    payload = {"snapshot": s, "state": state}
    with _connect() as con:
        con.execute(
            "INSERT INTO mobile_alert_events(created_at,fingerprint,opportunity_key,stage,direction,trade_function,entry_quality,confidence,delivered,delivery_channel,message,payload_json,error) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (current.isoformat(), fp, opp, stage, state.get("direction"), state.get("trade_function"),
             state.get("entry_quality_score"), state.get("confidence"), int(delivered), "TELEGRAM", message,
             json.dumps(payload, sort_keys=True, default=str), error),
        )
    return {"ok": delivered, "sent": delivered, "suppressed": False, "state": state,
            "message": message, "error": error, "opportunity_key": opp}


def mobile_alert_status(limit: int = 25) -> Dict[str, Any]:
    with _connect() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT id,created_at,stage,direction,trade_function,entry_quality,confidence,delivered,error FROM mobile_alert_events ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        ).fetchall()]
    return {
        "version": "PHASE_37",
        "advisory_only": True,
        "telegram_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")),
        "cooldown_seconds": DEFAULT_COOLDOWN_SECONDS,
        "last_alert": rows[0] if rows else None,
        "history": rows,
        "delivery_count": sum(1 for r in rows if r["delivered"]),
        "failure_count": sum(1 for r in rows if not r["delivered"]),
        "execution_note": "Alerts never place, modify, or close broker orders.",
    }
