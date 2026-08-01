"""APEX 50.6.2.2 durable canonical session context.

Small read-model persisted independently of process memory so weekend/replay consumers
(LTPE, readiness, replay) can recover the last known SPX reference spot and the
next-session institutional level universe after a deploy/restart.
"""
from __future__ import annotations
import json, os, sqlite3
from pathlib import Path
from typing import Any, Mapping, Optional

VERSION = "50.6.2.2_DURABLE_CANONICAL_CONTEXT"

def _default_path() -> str:
    explicit = os.getenv("APEX_CANONICAL_CONTEXT_DB")
    if explicit:
        return explicit
    if os.path.isdir("/data") and os.access("/data", os.W_OK):
        return "/data/apex_canonical_context.db"
    gov = os.getenv("APEX_GOVERNANCE_DB")
    if gov:
        return str(Path(gov).with_name("apex_canonical_context.db"))
    return str(Path(__file__).resolve().parents[1] / "apex_canonical_context.db")

DB_PATH = _default_path()

def init_db(path: Optional[str] = None) -> str:
    p = path or DB_PATH
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(p, timeout=10) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS canonical_session_context(
          symbol TEXT NOT NULL,
          target_session_date TEXT NOT NULL,
          source_session_date TEXT,
          generated_at TEXT NOT NULL,
          reference_spot REAL,
          prev_close REAL,
          levels_json TEXT NOT NULL,
          source TEXT NOT NULL,
          component_version TEXT,
          PRIMARY KEY(symbol,target_session_date)
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS ix_canonical_context_latest ON canonical_session_context(symbol,generated_at DESC)")
    return p

def _num(v: Any) -> Optional[float]:
    try:
        if v in (None, "", "[FEED REQUIRED]"):
            return None
        x=float(v)
        return x if x > 0 else None
    except Exception:
        return None

def save_from_morning_brief(payload: Mapping[str, Any], *, symbol: str="SPX", path: Optional[str]=None) -> dict:
    p=init_db(path)
    structured=payload.get("structured") if isinstance(payload.get("structured"), Mapping) else {}
    levels=structured.get("levels") if isinstance(structured.get("levels"), list) else []
    source=str(payload.get("source_session_date") or payload.get("session_date") or "") or None
    target=str(payload.get("target_session_date") or source or "")
    if not target:
        return {"ok":False,"error":"NO_TARGET_SESSION","version":VERSION}
    generated=str(payload.get("generated_at") or "")
    reference=_num(structured.get("spot")) or _num(payload.get("spot"))
    prev_close=None
    for row in levels:
        if isinstance(row, Mapping) and str(row.get("kind") or "").lower()=="prev_close":
            prev_close=_num(row.get("price")); break
    body=json.dumps(levels, separators=(",",":"), default=str)
    with sqlite3.connect(p, timeout=10) as c:
        c.execute("""INSERT INTO canonical_session_context
          (symbol,target_session_date,source_session_date,generated_at,reference_spot,prev_close,levels_json,source,component_version)
          VALUES(?,?,?,?,?,?,?,?,?)
          ON CONFLICT(symbol,target_session_date) DO UPDATE SET
          source_session_date=excluded.source_session_date,generated_at=excluded.generated_at,
          reference_spot=excluded.reference_spot,prev_close=excluded.prev_close,levels_json=excluded.levels_json,
          source=excluded.source,component_version=excluded.component_version""",
          (symbol.upper(),target,source,generated,reference,prev_close,body,"morning_brief",str(payload.get("version") or "")))
    return {"ok":True,"symbol":symbol.upper(),"source_session_date":source,"target_session_date":target,"reference_spot":reference,"prev_close":prev_close,"level_count":len(levels),"version":VERSION}

def latest(symbol: str="SPX", *, path: Optional[str]=None) -> Optional[dict]:
    p=init_db(path)
    with sqlite3.connect(p, timeout=10) as c:
        c.row_factory=sqlite3.Row
        row=c.execute("SELECT * FROM canonical_session_context WHERE symbol=? ORDER BY generated_at DESC LIMIT 1",(symbol.upper(),)).fetchone()
    if not row: return None
    out=dict(row)
    try: out["levels"]=json.loads(out.pop("levels_json") or "[]")
    except Exception: out["levels"]=[]
    out["version"]=VERSION
    return out
