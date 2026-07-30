"""APEX 50.2 persistent daily volume-profile history."""
from __future__ import annotations
import datetime as dt
import json
import os
import sqlite3
from typing import Any

DB_PATH = os.getenv("APEX_GOVERNANCE_DB", os.getenv("DB_PATH", "apex_governance.db"))


def _conn():
    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS apex_volume_profile_history (
        session_date TEXT NOT NULL, ticker TEXT NOT NULL, poc REAL, vah REAL, val REAL,
        payload_json TEXT, saved_at TEXT NOT NULL, PRIMARY KEY(session_date,ticker))""")
    return c


def save_profile(session_date: str, ticker: str, profile: dict[str, Any]) -> None:
    levels = (profile or {}).get("levels") or profile or {}
    def num(*keys):
        for key in keys:
            value = levels.get(key)
            try:
                if value is not None: return float(value)
            except (TypeError, ValueError): pass
        return None
    poc, vah, val = num("poc", "dev_poc"), num("vah"), num("val")
    if poc is None or vah is None or val is None:
        return
    with _conn() as c:
        c.execute("""INSERT INTO apex_volume_profile_history
          (session_date,ticker,poc,vah,val,payload_json,saved_at) VALUES(?,?,?,?,?,?,?)
          ON CONFLICT(session_date,ticker) DO UPDATE SET
          poc=excluded.poc,vah=excluded.vah,val=excluded.val,
          payload_json=excluded.payload_json,saved_at=excluded.saved_at""",
          (session_date, ticker.upper(), poc, vah, val, json.dumps(profile, default=str),
           dt.datetime.now(dt.timezone.utc).isoformat()))


def load_profile_context(ticker: str, current_date: str, lookback: int = 20) -> dict[str, Any]:
    with _conn() as c:
        rows = c.execute("""SELECT * FROM apex_volume_profile_history
          WHERE ticker=? AND session_date<? ORDER BY session_date DESC LIMIT ?""",
          (ticker.upper(), current_date, lookback)).fetchall()
    if not rows:
        return {}
    previous = rows[0]
    pocs = [float(r["poc"]) for r in rows if r["poc"] is not None]
    vahs = [float(r["vah"]) for r in rows if r["vah"] is not None]
    vals = [float(r["val"]) for r in rows if r["val"] is not None]
    return {
        "prev_poc": previous["poc"],
        "comp_poc": sum(pocs)/len(pocs) if pocs else None,
        "comp_vah": sum(vahs)/len(vahs) if vahs else None,
        "comp_val": sum(vals)/len(vals) if vals else None,
        "profile_history_sessions": len(rows),
    }
