"""APEX Trade Director Phase 34 — governed session allocation.

Tracks confirmed trades and recommends, but never executes, contract allocation.
The user's baseline progression is 1 -> 3 -> 4 -> 3 with up to five trades/day.
The fifth trade is adaptive and capped at three contracts. All recommendations
remain bounded by environment quality and remaining daily risk.
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
        status TEXT NOT NULL DEFAULT 'CONFIRMED',
        UNIQUE(session_date, created_at, ticker, side)
    )""")
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
                           created_at: Optional[str] = None,
                           session_date: Optional[str] = None) -> Dict[str, Any]:
    ts = created_at or datetime.now(ET).isoformat()
    day = _today(session_date)
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM session_allocation_trades WHERE session_date=?", (day,)).fetchone()[0]
        if count >= MAX_TRADES:
            return {"ok": False, "recorded": False, "reason": "DAILY_TRADE_LIMIT_REACHED", "session_date": day}
        cur = conn.execute("""INSERT OR IGNORE INTO session_allocation_trades
            (session_date, created_at, ticker, side, quantity, risk_dollars, environment_quality)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (day, ts, str(ticker).upper(), str(side).upper(), max(1, int(quantity)),
             max(0.0, float(risk_dollars or 0)), _quality(environment_quality)))
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
    quality = _quality(environment_quality)
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
        "version": "PHASE_34", "advisory_only": True, "confirmation_gated": True,
        "session_date": day, "max_trades": MAX_TRADES, "sequence": list(BASE_SEQUENCE),
        "trades_taken": trades_taken, "remaining_trade_slots": remaining_slots,
        "next_trade_number": next_trade, "planned_contracts": baseline,
        "recommended_contracts": recommendation, "environment_quality": quality,
        "allocation_gate": gate, "daily_risk_budget": float(daily_risk_budget),
        "used_risk_budget": round(used_risk, 2), "remaining_risk_budget": round(remaining, 2),
        "consecutive_losses": int(consecutive_losses), "reasons": reasons,
        "confirmed_trades": rows,
    }
