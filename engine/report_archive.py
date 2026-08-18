"""APEX 50.7.1 — Morning Readiness + Evening Recap review archive."""
from __future__ import annotations

from .canonical_persistence import connect as canonical_connect
import datetime as dt, hashlib, json, os, sqlite3
from typing import Any
from .persistent_store import persistent_sqlite_path
from .session_intelligence import classify_session

VERSION = "50.7.1_REPORT_REVIEW_ARCHIVE"
DB_PATH = persistent_sqlite_path("APEX_GOVERNANCE_DB", "apex_governance.db")

def _json(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), default=str)

def _today(payload: dict) -> str:
    for key in ("session_date", "target_session_date", "date"):
        v = payload.get(key)
        if v:
            return str(v)[:10]
    return classify_session().target_session_date

def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with canonical_connect(DB_PATH, timeout=10) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS apex5071_readiness_archive(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_date TEXT NOT NULL,
          captured_at TEXT NOT NULL,
          payload_hash TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          is_official INTEGER NOT NULL DEFAULT 0,
          version TEXT NOT NULL,
          UNIQUE(session_date,payload_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_apex5071_readiness_date
          ON apex5071_readiness_archive(session_date,captured_at);
        """)

def archive_readiness(payload: dict) -> dict:
    """Persist the first readiness report for a date and changed revisions only."""
    init_db()
    session_date = _today(payload)
    captured_at = dt.datetime.now(dt.timezone.utc).isoformat()
    body = _json(payload)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    with canonical_connect(DB_PATH, timeout=10) as c:
        count = c.execute("SELECT COUNT(*) FROM apex5071_readiness_archive WHERE session_date=?", (session_date,)).fetchone()[0]
        official = count == 0
        try:
            c.execute("INSERT INTO apex5071_readiness_archive(session_date,captured_at,payload_hash,payload_json,is_official,version) VALUES(?,?,?,?,?,?)",
                      (session_date,captured_at,digest,body,1 if official else 0,VERSION))
            saved = True
        except sqlite3.IntegrityError:
            saved = False
        total = c.execute("SELECT COUNT(*) FROM apex5071_readiness_archive WHERE session_date=?", (session_date,)).fetchone()[0]
    return {"archived": True, "saved": saved, "session_date": session_date, "is_official": official and saved, "revision_count": int(total), "version": VERSION}

def readiness_history(limit: int = 60) -> dict:
    init_db(); limit=max(1,min(int(limit),365))
    with canonical_connect(DB_PATH, timeout=10) as c:
        rows=c.execute("""SELECT session_date,MIN(captured_at),MAX(captured_at),COUNT(*),MAX(is_official)
                          FROM apex5071_readiness_archive GROUP BY session_date ORDER BY session_date DESC LIMIT ?""",(limit,)).fetchall()
    return {"ok":True,"count":len(rows),"items":[{"session_date":r[0],"first_captured_at":r[1],"last_captured_at":r[2],"revision_count":r[3],"official_available":bool(r[4])} for r in rows],"version":VERSION}

def get_readiness(session_date: str, revision: str = "official") -> dict | None:
    init_db()
    order = "is_official DESC, captured_at ASC" if revision == "official" else "captured_at DESC"
    with canonical_connect(DB_PATH, timeout=10) as c:
        row=c.execute(f"SELECT captured_at,payload_json,is_official FROM apex5071_readiness_archive WHERE session_date=? ORDER BY {order} LIMIT 1",(session_date,)).fetchone()
    if not row: return None
    payload=json.loads(row[1]); payload["archive"]={"session_date":session_date,"captured_at":row[0],"is_official":bool(row[2]),"version":VERSION}
    return payload

def report_catalog(limit: int = 60) -> dict:
    """Unified review index across readiness, Morning Brief and Evening Recap archives."""
    init_db(); limit=max(1,min(int(limit),365))
    dates={}
    with canonical_connect(DB_PATH, timeout=10) as c:
        for (d,) in c.execute("SELECT DISTINCT session_date FROM apex5071_readiness_archive ORDER BY session_date DESC LIMIT ?",(limit,)).fetchall(): dates.setdefault(d,{"session_date":d})["morning_readiness"]=True
        # APEX 49 tables may not exist on a brand-new DB.
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "apex49_morning_snapshots" in tables:
            for (d,) in c.execute("SELECT session_date FROM apex49_morning_snapshots ORDER BY session_date DESC LIMIT ?",(limit,)).fetchall(): dates.setdefault(d,{"session_date":d})["morning_brief"]=True
        if "apex49_evening_recaps" in tables:
            for d,score,grade in c.execute("SELECT session_date,score,grade FROM apex49_evening_recaps ORDER BY session_date DESC LIMIT ?",(limit,)).fetchall():
                x=dates.setdefault(d,{"session_date":d}); x.update({"evening_recap":True,"score":score,"grade":grade})
    items=sorted(dates.values(),key=lambda x:x["session_date"],reverse=True)[:limit]
    return {"ok":True,"count":len(items),"items":items,"version":VERSION}
