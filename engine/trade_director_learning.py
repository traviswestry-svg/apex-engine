"""APEX Trade Director Phase 6 — Trade Learning, Replay and Calibration.

Lazy SQLite persistence only.  No import-time database connection, market-data
request, scanner, thread, or broker action is created by this module.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_director_trades (
    trade_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    entered_at TEXT,
    closed_at TEXT,
    status TEXT NOT NULL,
    position_json TEXT NOT NULL,
    timeline_json TEXT NOT NULL,
    review_json TEXT,
    outcome_json TEXT,
    scoring_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_td_trades_closed_at
ON trade_director_trades(closed_at DESC);
"""


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def learning_db_path() -> str:
    configured = os.getenv("APEX_TRADE_LEARNING_DB", "").strip()
    if configured:
        return configured
    if os.path.isdir("/data") and os.access("/data", os.W_OK):
        return "/data/apex_trade_learning.db"
    return os.path.join(os.getcwd(), "apex_trade_learning.db")


def _connect() -> sqlite3.Connection:
    path = learning_db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=3.0)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def new_trade_id() -> str:
    return "ATD-" + uuid.uuid4().hex[:12].upper()


def archive_trade(position: Dict[str, Any], review: Optional[Dict[str, Any]] = None) -> str:
    trade_id = str(position.get("trade_id") or new_trade_id())
    now = _utc_now()
    status = str(position.get("status") or "CLOSED")
    timeline = list(position.get("recommendation_timeline") or [])
    closed_at = str((review or {}).get("exit_time") or position.get("closed_at") or now)
    with _connect() as conn:
        conn.execute(
            """INSERT INTO trade_director_trades
               (trade_id,ticker,side,entered_at,closed_at,status,position_json,
                timeline_json,review_json,outcome_json,scoring_json,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(trade_id) DO UPDATE SET
                 ticker=excluded.ticker, side=excluded.side,
                 entered_at=excluded.entered_at, closed_at=excluded.closed_at,
                 status=excluded.status, position_json=excluded.position_json,
                 timeline_json=excluded.timeline_json, review_json=excluded.review_json,
                 updated_at=excluded.updated_at""",
            (
                trade_id, str(position.get("ticker") or "SPX"), str(position.get("side") or ""),
                position.get("entered_at_iso") or position.get("entered_at"), closed_at, status,
                json.dumps(position, default=str), json.dumps(timeline, default=str),
                json.dumps(review, default=str) if review else None,
                None, None, now, now,
            ),
        )
    return trade_id


def _score_recommendations(timeline: List[Dict[str, Any]], outcome: Dict[str, Any]) -> Dict[str, Any]:
    pnl = outcome.get("realized_pnl")
    try:
        pnl = float(pnl) if pnl is not None else None
    except (TypeError, ValueError):
        pnl = None
    favorable = None if pnl is None else pnl > 0
    rows: List[Dict[str, Any]] = []
    for event in timeline:
        if event.get("kind") != "RECOMMENDATION":
            continue
        rec = str(event.get("recommendation") or "HOLD").upper()
        if favorable is None:
            score = 50
            verdict = "UNSCORED"
        elif favorable:
            score = {"HOLD": 90, "PROTECT_PROFIT": 82, "TRIM_50": 76, "TAKE_PARTIAL": 76, "EXIT": 62}.get(rec, 65)
            verdict = "SUPPORTED" if score >= 75 else "CONSERVATIVE"
        else:
            score = {"EXIT": 92, "TRIM_50": 84, "TAKE_PARTIAL": 84, "PROTECT_PROFIT": 76, "HOLD": 28}.get(rec, 55)
            verdict = "PROTECTIVE" if score >= 75 else "MISALIGNED"
        confidence = event.get("confidence")
        rows.append({
            "time": event.get("time"), "recommendation": rec,
            "trade_health": event.get("trade_health"), "confidence": confidence,
            "score": score, "verdict": verdict,
        })
    avg = round(sum(r["score"] for r in rows) / len(rows), 1) if rows else None
    return {
        "version": "PHASE_6",
        "method": "PROVISIONAL_OUTCOME_ALIGNMENT",
        "average_recommendation_score": avg,
        "recommendations_scored": len(rows),
        "events": rows,
        "note": "Scores compare management posture with the user-confirmed trade outcome; they are not proof of causal alpha.",
    }


def record_outcome(trade_id: str, outcome: Dict[str, Any]) -> Dict[str, Any]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM trade_director_trades WHERE trade_id=?", (trade_id,)).fetchone()
        if row is None:
            raise KeyError("trade not found")
        timeline = json.loads(row["timeline_json"] or "[]")
        normalized = {
            "exit_premium": outcome.get("exit_premium"),
            "realized_pnl": outcome.get("realized_pnl"),
            "max_favorable_excursion": outcome.get("max_favorable_excursion"),
            "max_adverse_excursion": outcome.get("max_adverse_excursion"),
            "post_exit_move_points": outcome.get("post_exit_move_points"),
            "followed_apex": outcome.get("followed_apex"),
            "notes": str(outcome.get("notes") or "").strip(),
            "confirmed_at": _utc_now(),
            "source": "USER_CONFIRMED",
        }
        scoring = _score_recommendations(timeline, normalized)
        conn.execute(
            "UPDATE trade_director_trades SET outcome_json=?, scoring_json=?, updated_at=? WHERE trade_id=?",
            (json.dumps(normalized, default=str), json.dumps(scoring, default=str), _utc_now(), trade_id),
        )
    return {"trade_id": trade_id, "outcome": normalized, "scoring": scoring}


def _decode(row: sqlite3.Row) -> Dict[str, Any]:
    def load(key: str, default: Any):
        try:
            return json.loads(row[key]) if row[key] else default
        except Exception:
            return default
    return {
        "trade_id": row["trade_id"], "ticker": row["ticker"], "side": row["side"],
        "entered_at": row["entered_at"], "closed_at": row["closed_at"], "status": row["status"],
        "position": load("position_json", {}), "timeline": load("timeline_json", []),
        "review": load("review_json", None), "outcome": load("outcome_json", None),
        "scoring": load("scoring_json", None), "updated_at": row["updated_at"],
    }


def get_trade(trade_id: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM trade_director_trades WHERE trade_id=?", (trade_id,)).fetchone()
    return _decode(row) if row else None


def trade_history(limit: int = 20) -> List[Dict[str, Any]]:
    limit = max(1, min(100, int(limit)))
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM trade_director_trades ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    return [_decode(r) for r in rows]


def calibration_scorecard() -> Dict[str, Any]:
    trades = trade_history(250)
    scored = [t for t in trades if t.get("scoring") and t["scoring"].get("average_recommendation_score") is not None]
    scores = [float(t["scoring"]["average_recommendation_score"]) for t in scored]
    by_action: Dict[str, List[float]] = {}
    for trade in scored:
        for event in trade["scoring"].get("events") or []:
            by_action.setdefault(str(event.get("recommendation") or "UNKNOWN"), []).append(float(event.get("score") or 0))
    actions = [{"recommendation": k, "samples": len(v), "average_score": round(sum(v)/len(v), 1)} for k, v in by_action.items()]
    actions.sort(key=lambda x: (-x["samples"], x["recommendation"]))
    return {
        "version": "PHASE_6", "trades_archived": len(trades), "trades_scored": len(scored),
        "overall_score": round(sum(scores)/len(scores), 1) if scores else None,
        "by_recommendation": actions,
        "calibration_status": "LEARNING" if len(scored) < 30 else "CALIBRATING" if len(scored) < 100 else "ESTABLISHED",
        "minimum_sample_note": "Treat recommendation statistics as provisional until at least 30 user-confirmed outcomes are recorded.",
        "database": learning_db_path(),
    }
