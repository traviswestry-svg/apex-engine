"""APEX 14 Sprint 10.5: Institutional Replay 2.0.

Creates immutable, decision-time-only replay packages from frozen Decision
Intelligence artifacts. No market outcome or information timestamped after the
canonical decision may enter LIVE replay mode.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import sqlite3
import uuid
from typing import Any

from . import institutional_governance as gov
from . import decision_intelligence_core as core
from . import confidence_attribution_engine as attribution
from . import institutional_evidence_graph as graphs

VERSION = "14.0.10.5"
SCHEMA_VERSION = "apex.institutional_replay.v2"


def _now() -> str: return dt.datetime.now(dt.timezone.utc).isoformat()
def _json(v: Any) -> str: return json.dumps(v, sort_keys=True, separators=(",", ":"), default=str)
def _load(v: Any, default: Any = None) -> Any:
    if v in (None, ""): return [] if default == [] else ({} if default is None else default)
    try: return json.loads(v)
    except Exception: return [] if default == [] else ({} if default is None else default)

def _conn():
    c=sqlite3.connect(gov.DB_PATH); c.row_factory=sqlite3.Row; c.execute("PRAGMA foreign_keys=ON"); return c

def init_db() -> dict[str, Any]:
    core.init_db()
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS institutional_replays(
          replay_id TEXT PRIMARY KEY,
          decision_id TEXT NOT NULL UNIQUE,
          explainability_id TEXT NOT NULL,
          replay_mode TEXT NOT NULL,
          schema_version TEXT NOT NULL,
          engine_version TEXT NOT NULL,
          frame_count INTEGER NOT NULL,
          replay_json TEXT NOT NULL,
          limitations_json TEXT NOT NULL,
          integrity_hash TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(decision_id) REFERENCES decision_intelligence_records(decision_id)
        );
        CREATE INDEX IF NOT EXISTS idx_replay_created ON institutional_replays(created_at);
        """)
    return {"ok":True,"schema_version":SCHEMA_VERSION,"build_version":VERSION}

def _iso(value: Any) -> str:
    return str(value or "")

def _frames(record: dict[str, Any]) -> list[dict[str, Any]]:
    cutoff=_iso(record.get("observed_at"))
    evidence=[e for e in record.get("evidence") or [] if _iso(e.get("observed_at")) <= cutoff]
    timeline=[t for t in record.get("timeline") or [] if _iso(t.get("event_at")) <= cutoff]
    if not timeline:
        timeline=[{"event_at":cutoff,"event_type":"DECISION_CAPTURED","event":{"confidence":record.get("confidence"),"recommendation":record.get("recommendation")}}]
    frames=[]
    for idx,t in enumerate(sorted(timeline,key=lambda x:(_iso(x.get("event_at")),str(x.get("timeline_event_id") or "")))):
        at=_iso(t.get("event_at")); ev=t.get("event") or {}
        visible=[e for e in evidence if _iso(e.get("observed_at")) <= at]
        frames.append({
            "frame_index":idx,
            "event_at":at,
            "event_type":t.get("event_type") or "DECISION_EVENT",
            "recommendation":ev.get("recommendation",record.get("recommendation")),
            "confidence":ev.get("confidence",record.get("confidence")),
            "event":ev,
            "visible_evidence_ids":[e.get("evidence_id") for e in visible],
            "visible_evidence_count":len(visible),
            "look_ahead_blocked":True,
        })
    return frames

def create(identifier: str, actor: str="SYSTEM") -> dict[str, Any]:
    init_db(); record=core.get(identifier)
    if record is None: return {"ok":False,"status":"UNAVAILABLE","error":"decision_not_found"}
    with _conn() as c:
        row=c.execute("SELECT replay_id,integrity_hash FROM institutional_replays WHERE decision_id=?",(record["decision_id"],)).fetchone()
        if row: return {"ok":True,"status":"IMMUTABLE_EXISTS","replay_id":row["replay_id"],"integrity_hash":row["integrity_hash"],"created":False,"production_effect":"NONE"}
    attr=attribution.explain(identifier); graph=graphs.explain(identifier)
    frames=_frames(record)
    replay={
      "decision_id":record["decision_id"],"recommendation_id":record["recommendation_id"],"explainability_id":record["explainability_id"],
      "mode":"LIVE_DECISION_TIME","cutoff_at":record.get("observed_at"),"frames":frames,
      "evidence":record.get("evidence") or [],"contributions":record.get("contributions") or [],
      "confidence_attribution":attr if attr.get("ok") else None,"evidence_graph":graph if graph.get("ok") else None,
      "final_state":{"recommendation":record.get("recommendation"),"direction":record.get("direction"),"confidence":record.get("confidence"),"risk_level":record.get("risk_level")},
      "outcome":None,"future_information_included":False,
    }
    limitations=["Live replay includes only information available at or before the canonical decision timestamp","No market outcome is included","No confidence or recommendation recomputation","Replay is immutable and audit-hashed"]
    raw=_json({"schema_version":SCHEMA_VERSION,"replay":replay,"limitations":limitations}); ih=hashlib.sha256(raw.encode()).hexdigest(); rid=str(uuid.uuid4()); created=_now()
    with _conn() as c:
        c.execute("INSERT INTO institutional_replays VALUES(?,?,?,?,?,?,?,?,?,?,?)",(rid,record["decision_id"],record["explainability_id"],"LIVE_DECISION_TIME",SCHEMA_VERSION,VERSION,len(frames),_json(replay),_json(limitations),ih,created))
    gov.audit("CREATE_INSTITUTIONAL_REPLAY","institutional_replay",rid,new={"decision_id":record["decision_id"],"integrity_hash":ih},actor=actor,explanation="Immutable decision-time replay created without look-ahead")
    return {"ok":True,"status":"CREATED","replay_id":rid,"decision_id":record["decision_id"],"integrity_hash":ih,"created":True,"production_effect":"NONE"}

def get(identifier: str) -> dict[str, Any]:
    init_db(); record=core.get(identifier)
    if record is None:return {"ok":False,"status":"UNAVAILABLE","error":"decision_not_found"}
    with _conn() as c: row=c.execute("SELECT * FROM institutional_replays WHERE decision_id=?",(record["decision_id"],)).fetchone()
    if not row:return {"ok":False,"status":"NOT_BUILT","error":"replay_not_found","decision_id":record["decision_id"]}
    d=dict(row); d["replay"]=_load(d.pop("replay_json")); d["limitations"]=_load(d.pop("limitations_json"),[])
    return {"ok":True,"status":"READY",**d,"future_information_allowed":False,"production_effect":"NONE"}

def list_replays(limit:int=100)->list[dict[str,Any]]:
    init_db()
    with _conn() as c: rows=c.execute("SELECT replay_id,decision_id,explainability_id,replay_mode,frame_count,integrity_hash,created_at FROM institutional_replays ORDER BY created_at DESC LIMIT ?",(max(1,min(int(limit),1000)),)).fetchall()
    return [dict(r) for r in rows]

def status()->dict[str,Any]:
    init_db()
    with _conn() as c: count=c.execute("SELECT COUNT(*) n FROM institutional_replays").fetchone()["n"]
    return {"status":"READY","schema_version":SCHEMA_VERSION,"build_version":VERSION,"replay_count":count,"future_information_allowed":False,"outcomes_in_live_replay":False,"decision_mutation_enabled":False,"confidence_mutation_enabled":False,"production_effect":"NONE"}
