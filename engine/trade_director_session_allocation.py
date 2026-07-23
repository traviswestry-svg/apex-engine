"""APEX Trade Director Phase 34 — governed session allocation.

Tracks confirmed trades and recommends, but never executes, contract allocation.
The user's baseline progression is 1 -> 3 -> 4 -> 3 with up to five trades/day.
The fifth trade is adaptive and capped at three contracts. Recommendations are
bounded by selected trade-function fit and remaining daily risk; there is no
universal good/bad market classification.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
MAX_TRADES = 5
BASE_SEQUENCE = (1, 3, 4, 3, 3)
DEFAULT_DAILY_RISK = 2000.0


def _db_path() -> Path:
    return Path(os.getenv("APEX_GOVERNANCE_DB", "apex_governance.db"))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS session_allocation_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_date TEXT NOT NULL,
        created_at TEXT NOT NULL,
        ticker TEXT NOT NULL,
        side TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        risk_dollars REAL NOT NULL DEFAULT 0,
        environment_quality TEXT NOT NULL DEFAULT 'UNKNOWN',
        trade_function TEXT NOT NULL DEFAULT 'UNSPECIFIED',
        style_fit_grade TEXT NOT NULL DEFAULT 'UNRATED',
        style_fit_score REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'CONFIRMED',
        UNIQUE(session_date, created_at, ticker, side)
    )""")
    existing = {r[1] for r in conn.execute("PRAGMA table_info(session_allocation_trades)").fetchall()}
    for name, ddl in (("trade_function", "TEXT NOT NULL DEFAULT 'UNSPECIFIED'"),
                      ("style_fit_grade", "TEXT NOT NULL DEFAULT 'UNRATED'"),
                      ("style_fit_score", "REAL NOT NULL DEFAULT 0")):
        if name not in existing:
            conn.execute(f"ALTER TABLE session_allocation_trades ADD COLUMN {name} {ddl}")
    conn.commit()
    return conn


def _today(session_date: Optional[str] = None) -> str:
    return session_date or datetime.now(ET).date().isoformat()


def _quality(value: Any) -> str:
    raw = str(value or "UNKNOWN").strip().upper().replace(" ", "_")
    aliases = {"A+": "HIGH_QUALITY", "A": "HIGH_QUALITY", "HIGH": "HIGH_QUALITY",
               "GOOD": "FAVORABLE", "NORMAL": "FAVORABLE", "LOW": "POOR",
               "STAND_DOWN": "POOR", "NO_TRADE": "POOR"}
    return aliases.get(raw, raw)


def record_confirmed_trade(*, ticker: str, side: str, quantity: int,
                           risk_dollars: float = 0.0,
                           environment_quality: str = "UNKNOWN",
                           trade_function: str = "UNSPECIFIED",
                           style_fit_grade: str = "UNRATED",
                           style_fit_score: float = 0.0,
                           created_at: Optional[str] = None,
                           session_date: Optional[str] = None) -> Dict[str, Any]:
    ts = created_at or datetime.now(ET).isoformat()
    day = _today(session_date)
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM session_allocation_trades WHERE session_date=?", (day,)).fetchone()[0]
        if count >= MAX_TRADES:
            return {"ok": False, "recorded": False, "reason": "DAILY_TRADE_LIMIT_REACHED", "session_date": day}
        cur = conn.execute("""INSERT OR IGNORE INTO session_allocation_trades
            (session_date, created_at, ticker, side, quantity, risk_dollars, environment_quality, trade_function, style_fit_grade, style_fit_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (day, ts, str(ticker).upper(), str(side).upper(), max(1, int(quantity)),
             max(0.0, float(risk_dollars or 0)), _quality(environment_quality),
             str(trade_function or "UNSPECIFIED").upper(), str(style_fit_grade or "UNRATED").upper(),
             max(0.0, min(100.0, float(style_fit_score or 0)))))
        conn.commit()
        return {"ok": True, "recorded": cur.rowcount == 1, "session_date": day,
                "trade_number": count + 1 if cur.rowcount == 1 else count}


def reset_session(session_date: Optional[str] = None) -> Dict[str, Any]:
    day = _today(session_date)
    with _connect() as conn:
        cur = conn.execute("DELETE FROM session_allocation_trades WHERE session_date=?", (day,))
        conn.commit()
    return {"ok": True, "session_date": day, "deleted": cur.rowcount}


def build_session_allocation(*, environment_quality: str = "UNKNOWN",
                             trade_function: str = "QUICK_SCALP",
                             style_fit_grade: Optional[str] = None,
                             style_fit_score: Optional[float] = None,
                             daily_risk_budget: float = DEFAULT_DAILY_RISK,
                             remaining_risk_budget: Optional[float] = None,
                             estimated_risk_per_contract: float = 0.0,
                             consecutive_losses: int = 0,
                             session_date: Optional[str] = None) -> Dict[str, Any]:
    day = _today(session_date)
    with _connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM session_allocation_trades WHERE session_date=? ORDER BY id", (day,)).fetchall()]
    trades_taken = len(rows)
    remaining_slots = max(0, MAX_TRADES - trades_taken)
    next_trade = trades_taken + 1 if remaining_slots else None
    baseline = BASE_SEQUENCE[trades_taken] if remaining_slots else 0
    quality = _quality(environment_quality)  # backward-compatible display only
    function = str(trade_function or "QUICK_SCALP").strip().upper()
    style_mode = style_fit_grade is not None or style_fit_score is not None
    fit_grade = str(style_fit_grade or "UNRATED").strip().upper()
    fit_score = max(0.0, min(100.0, float(style_fit_score or 0)))
    used_risk = sum(float(r.get("risk_dollars") or 0) for r in rows)
    remaining = max(0.0, float(remaining_risk_budget if remaining_risk_budget is not None else daily_risk_budget - used_risk))
    risk_cap = baseline
    if estimated_risk_per_contract and estimated_risk_per_contract > 0:
        risk_cap = min(risk_cap, int(remaining // float(estimated_risk_per_contract)))

    recommendation = min(baseline, max(0, risk_cap))
    reasons = []
    gate = "ELIGIBLE"
    if not remaining_slots:
        recommendation, gate = 0, "DAILY_TRADE_LIMIT_REACHED"
        reasons.append("Maximum of five confirmed trades reached.")
    elif consecutive_losses >= 2:
        recommendation, gate = 0, "LOSS_LOCKOUT"
        reasons.append("Two consecutive losses require a session lockout or explicit human override.")
    elif style_mode and (fit_grade in {"INSUFFICIENT_DATA", "UNRATED", "D", "F"} or fit_score < 55):
        recommendation, gate = min(1, recommendation), "STYLE_FIT_REDUCED"
        reasons.append(f"{function} does not have sufficient validated style fit; allocation is reduced to discovery size.")
    elif style_mode and baseline >= 4 and fit_grade != "A+":
        recommendation, gate = min(3, recommendation), "STYLE_FIT_REDUCED"
        reasons.append("Four contracts are reserved for an A+ fit in the selected trade function.")
    elif style_mode and fit_grade == "A+":
        reasons.append(f"A+ {function} fit supports the planned allocation, subject to risk budget and confirmation.")
    elif style_mode:
        reasons.append(f"{fit_grade} {function} fit supports the planned allocation up to the governed cap.")
    elif quality in {"POOR", "UNTRADEABLE", "CLOSED", "UNKNOWN"}:
        recommendation, gate = min(1, recommendation), "REDUCED"
        reasons.append("Environment is not confirmed favorable; allocation is reduced to discovery size.")
    elif quality == "FAVORABLE" and baseline >= 4:
        recommendation, gate = min(3, recommendation), "REDUCED"
        reasons.append("Four contracts are reserved for a high-quality environment.")
    elif quality == "HIGH_QUALITY":
        reasons.append("High-quality environment supports the planned allocation, subject to risk budget.")
    if recommendation < baseline and remaining_slots and not reasons:
        reasons.append("Remaining risk budget reduced the planned allocation.")

    return {
        "version": "PHASE_35", "advisory_only": True, "confirmation_gated": True,
        "session_date": day, "max_trades": MAX_TRADES, "sequence": list(BASE_SEQUENCE),
        "trades_taken": trades_taken, "remaining_trade_slots": remaining_slots,
        "next_trade_number": next_trade, "planned_contracts": baseline,
        "recommended_contracts": recommendation, "environment_quality": quality,
        "trade_function": function, "style_fit_grade": fit_grade, "style_fit_score": fit_score,
        "allocation_gate": gate, "daily_risk_budget": float(daily_risk_budget),
        "used_risk_budget": round(used_risk, 2), "remaining_risk_budget": round(remaining, 2),
        "consecutive_losses": int(consecutive_losses), "reasons": reasons,
        "confirmed_trades": rows,
    }
