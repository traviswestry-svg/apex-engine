"""engine/director/store.py — directive & outcome logging (Part 18).

Every Active Trade Director decision is persisted so APEX can later learn which
HOLD signals help, which EXITs are early, which flow reversals precede losses,
which hold levels work, and which regimes favour scalping. Uses the same SQLite
database as the rest of APEX (DB_PATH) with a dedicated table; degrades to a
no-op if the DB can't be initialised (never blocks a trading decision).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional


_DB_PATH = os.getenv("DIRECTOR_DB_PATH", os.getenv("DB_PATH", "apex_tracking.db"))
_LOCK = threading.RLock()
_ENABLED = True
_INIT_DONE = False


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_store() -> bool:
    """Create the directive table. Returns True if logging is available."""
    global _ENABLED, _INIT_DONE
    with _LOCK:
        if _INIT_DONE:
            return _ENABLED
        _INIT_DONE = True
        try:
            db_dir = os.path.dirname(_DB_PATH)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
            conn = _connect()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS director_directives (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts              TEXT,
                    ts_et           TEXT,
                    symbol          TEXT,
                    directive       TEXT,
                    position_state  TEXT,
                    side            TEXT,
                    trade_type      TEXT,
                    confidence      INTEGER,
                    urgency         TEXT,
                    thesis_status   TEXT,
                    flow_state      TEXT,
                    flow_change_pct REAL,
                    auction_state   TEXT,
                    gamma_regime    TEXT,
                    poc_migration   TEXT,
                    hold_level      REAL,
                    hold_source     TEXT,
                    invalidation    REAL,
                    price           REAL,
                    target_1        REAL,
                    target_2        REAL,
                    target_3        REAL,
                    reason          TEXT,
                    next_action     TEXT,
                    next_trigger    TEXT,
                    prev_directive  TEXT,
                    state_transition TEXT,
                    position_source TEXT,
                    trade_id        TEXT,
                    position_id     TEXT,
                    outcome         TEXT,
                    outcome_pnl     REAL,
                    payload         TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dd_symbol_ts ON director_directives(symbol, ts);")
            conn.commit()
            conn.close()
            _ENABLED = True
        except Exception as e:  # pragma: no cover - environment dependent
            print(f"Director directive logging DISABLED — DB init failed at '{_DB_PATH}': {e}", flush=True)
            _ENABLED = False
        return _ENABLED


def log_directive(directive: Dict[str, Any]) -> Optional[int]:
    """Persist one directive dict (the Directive.to_dict()). Returns row id or None."""
    if not init_store():
        return None
    d = directive or {}
    pos = d.get("position") or {}
    hold_src = d.get("hold_level_source") or ""
    try:
        with _LOCK:
            conn = _connect()
            cur = conn.execute(
                """
                INSERT INTO director_directives (
                    ts, ts_et, symbol, directive, position_state, side, trade_type,
                    confidence, urgency, thesis_status, flow_state, flow_change_pct,
                    auction_state, gamma_regime, poc_migration, hold_level, hold_source,
                    invalidation, price, target_1, target_2, target_3, reason,
                    next_action, next_trigger, prev_directive, state_transition,
                    position_source, trade_id, position_id, outcome, outcome_pnl, payload
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    d.get("updated_at"), d.get("updated_at_et"), d.get("symbol"),
                    d.get("directive"), d.get("position_state"), d.get("side"), d.get("trade_type"),
                    int(d.get("confidence") or 0), d.get("urgency"), d.get("thesis_status"),
                    d.get("flow_state"), float(d.get("flow_change_pct") or 0.0),
                    d.get("auction_state"), (d.get("conflict") or {}).get("gamma_regime") or _gamma_from(d),
                    d.get("poc_migration"), _num(d.get("hold_level")), hold_src,
                    _num(d.get("invalidation_level")), _num((pos or {}).get("entry_price")) or _price_from(d),
                    _num(d.get("target_1")), _num(d.get("target_2")), _num(d.get("target_3")),
                    d.get("reason"), d.get("next_action"), d.get("next_action_trigger"),
                    d.get("previous_directive"), d.get("state_transition"),
                    (pos or {}).get("source"), (pos or {}).get("bracket_id") or "", (pos or {}).get("osi_key") or "",
                    None, None, json.dumps(d)[:60000],
                ),
            )
            conn.commit()
            rid = cur.lastrowid
            conn.close()
            return rid
    except Exception as e:  # pragma: no cover
        print(f"Director log_directive failed: {e}", flush=True)
        return None


def recent_directives(symbol: str = "SPX", limit: int = 50) -> List[Dict[str, Any]]:
    if not init_store():
        return []
    try:
        with _LOCK:
            conn = _connect()
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM director_directives WHERE symbol=? ORDER BY id DESC LIMIT ?",
                (symbol.upper(), int(limit)),
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
    except Exception:
        return []


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _gamma_from(d: Dict[str, Any]) -> str:
    fa = d.get("flow_acceleration") or {}
    return d.get("gamma_regime") or ""


def _price_from(d: Dict[str, Any]) -> Optional[float]:
    return _num(d.get("price"))
