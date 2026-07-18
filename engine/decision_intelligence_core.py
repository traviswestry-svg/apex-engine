"""APEX 14 Sprint 10.1: immutable Decision Intelligence Core.

Persists canonical institutional decisions and evidence available at decision time.
This module is observational: it never changes recommendation, confidence, risk,
execution, or production-governance behavior.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import sqlite3
import uuid
from typing import Any, Mapping

from . import institutional_governance as gov
from .institutional_decision_object import build_canonical_institutional_decision

VERSION = "14.0.10.1"
SCHEMA_VERSION = "apex.decision_intelligence.v1"
EVIDENCE_SCHEMA_VERSION = "apex.decision_evidence.v1"
CONTRIBUTION_SCHEMA_VERSION = "apex.decision_contribution.v1"
TIMELINE_SCHEMA_VERSION = "apex.decision_timeline.v1"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _load(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return {} if default is None else default
    try:
        return json.loads(value)
    except Exception:
        return {} if default is None else default


def _conn():
    c = sqlite3.connect(gov.DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_db() -> dict[str, Any]:
    gov.init_db()
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS decision_intelligence_records(
          decision_id TEXT PRIMARY KEY,
          recommendation_id TEXT NOT NULL UNIQUE,
          explainability_id TEXT NOT NULL UNIQUE,
          observed_at TEXT NOT NULL,
          ticker TEXT NOT NULL,
          recommendation TEXT NOT NULL,
          direction TEXT NOT NULL,
          confidence REAL,
          conviction REAL,
          risk_level TEXT,
          status TEXT NOT NULL,
          schema_version TEXT NOT NULL,
          engine_version TEXT NOT NULL,
          decision_json TEXT NOT NULL,
          provenance_json TEXT NOT NULL,
          limitations_json TEXT NOT NULL,
          integrity_hash TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_di_observed ON decision_intelligence_records(observed_at);
        CREATE TABLE IF NOT EXISTS decision_evidence_records(
          evidence_id TEXT PRIMARY KEY,
          decision_id TEXT NOT NULL,
          category TEXT NOT NULL,
          polarity TEXT NOT NULL,
          source_name TEXT,
          observed_at TEXT NOT NULL,
          evidence_json TEXT NOT NULL,
          provenance_json TEXT NOT NULL,
          schema_version TEXT NOT NULL,
          integrity_hash TEXT NOT NULL,
          FOREIGN KEY(decision_id) REFERENCES decision_intelligence_records(decision_id)
        );
        CREATE INDEX IF NOT EXISTS idx_di_evidence ON decision_evidence_records(decision_id,category);
        CREATE TABLE IF NOT EXISTS decision_contribution_records(
          contribution_id TEXT PRIMARY KEY,
          decision_id TEXT NOT NULL,
          contributor TEXT NOT NULL,
          direction TEXT NOT NULL,
          contribution REAL NOT NULL,
          reliability REAL,
          freshness TEXT,
          explanation TEXT,
          schema_version TEXT NOT NULL,
          integrity_hash TEXT NOT NULL,
          FOREIGN KEY(decision_id) REFERENCES decision_intelligence_records(decision_id)
        );
        CREATE INDEX IF NOT EXISTS idx_di_contrib ON decision_contribution_records(decision_id);
        CREATE TABLE IF NOT EXISTS decision_timeline_records(
          timeline_event_id TEXT PRIMARY KEY,
          decision_id TEXT NOT NULL,
          event_at TEXT NOT NULL,
          event_type TEXT NOT NULL,
          event_json TEXT NOT NULL,
          schema_version TEXT NOT NULL,
          integrity_hash TEXT NOT NULL,
          FOREIGN KEY(decision_id) REFERENCES decision_intelligence_records(decision_id)
        );
        CREATE INDEX IF NOT EXISTS idx_di_timeline ON decision_timeline_records(decision_id,event_at);
        """)
    return {"ok": True, "schema_version": SCHEMA_VERSION, "build_version": VERSION}


def _risk_level(decision: Mapping[str, Any]) -> str:
    risks = decision.get("risks") or []
    if isinstance(risks, Mapping):
        return str(risks.get("level") or risks.get("risk") or "UNKNOWN").upper()
    return "ELEVATED" if len(risks) >= 3 else ("MODERATE" if risks else "LOW")


def _evidence_rows(decision: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    consensus = decision.get("consensus") or {}
    for source in consensus.get("sources") or []:
        direction = str(source.get("direction") or "NEUTRAL").upper()
        dominant = str(consensus.get("dominant_direction") or "NEUTRAL").upper()
        polarity = "SUPPORTING" if direction == dominant and dominant != "NEUTRAL" else ("CONFLICTING" if direction not in {"NEUTRAL", dominant} else "NEUTRAL")
        rows.append({
            "category": str(source.get("source") or "CONSENSUS").upper(),
            "polarity": polarity,
            "source_name": source.get("source"),
            "observed_at": decision.get("timestamp") or _now(),
            "evidence": dict(source),
            "provenance": {"origin": "institutional_consensus.sources", "post_hoc": False},
        })
    evidence = ((decision.get("evidence_and_provenance") or {}).get("evidence") or {})
    if isinstance(evidence, Mapping):
        for key, value in sorted(evidence.items()):
            if value in (None, {}, [], ""):
                continue
            rows.append({
                "category": str(key).upper(), "polarity": "OBSERVED", "source_name": str(key),
                "observed_at": decision.get("timestamp") or _now(), "evidence": value,
                "provenance": {"origin": "canonical_decision.evidence", "post_hoc": False},
            })
    for kind, values in (("RISK", decision.get("risks") or []), ("INVALIDATION", decision.get("invalidation") or [])):
        if isinstance(values, Mapping): values = [values]
        for value in values if isinstance(values, list) else []:
            rows.append({
                "category": kind, "polarity": "CONFLICTING" if kind == "RISK" else "BOUNDARY",
                "source_name": kind.lower(), "observed_at": decision.get("timestamp") or _now(),
                "evidence": value, "provenance": {"origin": f"canonical_decision.{kind.lower()}", "post_hoc": False},
            })
    return rows


def capture(last_result: Mapping[str, Any], *, recommendation_id: str, actor: str = "SYSTEM", session_state: str | None = None) -> dict[str, Any]:
    init_db()
    rid = str(recommendation_id or "").strip()
    if not rid:
        return {"ok": False, "status": "UNAVAILABLE", "error": "recommendation_id is required"}
    with _conn() as c:
        existing = c.execute("SELECT decision_id,integrity_hash FROM decision_intelligence_records WHERE recommendation_id=?", (rid,)).fetchone()
    if existing:
        return {"ok": True, "status": "IMMUTABLE_EXISTS", "decision_id": existing["decision_id"], "integrity_hash": existing["integrity_hash"], "created": False}

    decision = build_canonical_institutional_decision(last_result, recommendation_id=rid, session_state=session_state)
    did, xid, created = str(uuid.uuid4()), str(uuid.uuid4()), _now()
    limitations = [
        "Explanation contains only evidence available in the captured canonical decision",
        "No recommendation or confidence calculation is changed",
        "No future outcome is included",
        "Decision Quality Score is not implemented in Sprint 10.1",
    ]
    identity = {"decision_id": did, "recommendation_id": rid, "explainability_id": xid, "observed_at": decision.get("timestamp"), "decision": decision}
    ih = hashlib.sha256(_json(identity).encode()).hexdigest()
    confidence = decision.get("conviction", {}).get("confidence") if isinstance(decision.get("conviction"), Mapping) else None
    if confidence is None: confidence = decision.get("conviction", {}).get("score") if isinstance(decision.get("conviction"), Mapping) else None
    conviction = decision.get("conviction", {}).get("score") if isinstance(decision.get("conviction"), Mapping) else None
    with _conn() as c:
        c.execute("INSERT INTO decision_intelligence_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            did, rid, xid, str(decision.get("timestamp") or created), str(decision.get("ticker") or "SPX"),
            str(decision.get("action") or "NO_TRADE"), str(decision.get("direction") or "NEUTRAL"), confidence, conviction,
            _risk_level(decision), str(decision.get("status") or "FAIL_CLOSED"), SCHEMA_VERSION, VERSION,
            _json(decision), _json({"canonical_schema": decision.get("schema_version"), "actor": actor, "post_hoc": False}),
            _json(limitations), ih, created,
        ))
        for row in _evidence_rows(decision):
            eid = str(uuid.uuid4()); raw = _json({"decision_id": did, **row}); eh = hashlib.sha256(raw.encode()).hexdigest()
            c.execute("INSERT INTO decision_evidence_records VALUES(?,?,?,?,?,?,?,?,?,?)", (eid,did,row["category"],row["polarity"],row.get("source_name"),str(row["observed_at"]),_json(row["evidence"]),_json(row["provenance"]),EVIDENCE_SCHEMA_VERSION,eh))
        for item in (decision.get("confidence_attribution") or {}).get("contributors") or []:
            cid = str(uuid.uuid4()); raw = _json({"decision_id":did,"item":item}); ch=hashlib.sha256(raw.encode()).hexdigest()
            c.execute("INSERT INTO decision_contribution_records VALUES(?,?,?,?,?,?,?,?,?,?)", (cid,did,str(item.get("engine") or "UNKNOWN"),str(item.get("direction") or "NEUTRAL"),float(item.get("contribution") or 0.0),item.get("reliability"),str(item.get("freshness") or ""),str(item.get("explanation") or ""),CONTRIBUTION_SCHEMA_VERSION,ch))
        timeline = decision.get("evolution_timeline") or []
        if not timeline:
            timeline = [{"event_type":"DECISION_CAPTURED","timestamp":decision.get("timestamp"),"recommendation":decision.get("action"),"confidence":confidence}]
        for item in timeline:
            tid=str(uuid.uuid4()); event_at=str(item.get("event_at") or item.get("timestamp") or decision.get("timestamp") or created); raw=_json({"decision_id":did,"event_at":event_at,"event":item}); th=hashlib.sha256(raw.encode()).hexdigest()
            c.execute("INSERT INTO decision_timeline_records VALUES(?,?,?,?,?,?,?)",(tid,did,event_at,str(item.get("event_type") or item.get("type") or "DECISION_EVENT"),_json(item),TIMELINE_SCHEMA_VERSION,th))
    gov.audit("CAPTURE_DECISION_INTELLIGENCE", "decision_intelligence", did, new={"recommendation_id":rid,"integrity_hash":ih}, actor=actor, explanation="Immutable decision-time evidence captured")
    return {"ok":True,"status":"CAPTURED","decision_id":did,"explainability_id":xid,"integrity_hash":ih,"created":True,"production_effect":"NONE"}


def get(identifier: str) -> dict[str, Any] | None:
    init_db()
    with _conn() as c:
        row=c.execute("SELECT * FROM decision_intelligence_records WHERE decision_id=? OR recommendation_id=? OR explainability_id=?",(identifier,identifier,identifier)).fetchone()
    if not row:return None
    d=dict(row); d["decision"]=_load(d.pop("decision_json")); d["provenance"]=_load(d.pop("provenance_json")); d["limitations"]=_load(d.pop("limitations_json"),[])
    d["evidence"]=evidence(d["decision_id"]); d["contributions"]=contributions(d["decision_id"]); d["timeline"]=timeline(d["decision_id"])
    return d


def evidence(decision_id: str) -> list[dict[str, Any]]:
    init_db()
    with _conn() as c: rows=c.execute("SELECT * FROM decision_evidence_records WHERE decision_id=? ORDER BY category,evidence_id",(decision_id,)).fetchall()
    return [dict(r)|{"evidence":_load(r["evidence_json"]),"provenance":_load(r["provenance_json"])} for r in rows]


def contributions(decision_id: str) -> list[dict[str, Any]]:
    init_db()
    with _conn() as c: rows=c.execute("SELECT * FROM decision_contribution_records WHERE decision_id=? ORDER BY contribution DESC,contributor",(decision_id,)).fetchall()
    return [dict(r) for r in rows]


def timeline(decision_id: str) -> list[dict[str, Any]]:
    init_db()
    with _conn() as c: rows=c.execute("SELECT * FROM decision_timeline_records WHERE decision_id=? ORDER BY event_at,timeline_event_id",(decision_id,)).fetchall()
    return [dict(r)|{"event":_load(r["event_json"])} for r in rows]


def list_records(limit: int = 100) -> list[dict[str, Any]]:
    init_db()
    with _conn() as c: rows=c.execute("SELECT decision_id,recommendation_id,explainability_id,observed_at,ticker,recommendation,direction,confidence,conviction,risk_level,status,integrity_hash FROM decision_intelligence_records ORDER BY observed_at DESC LIMIT ?",(max(1,min(int(limit),1000)),)).fetchall()
    return [dict(r) for r in rows]


def status() -> dict[str, Any]:
    init_db()
    with _conn() as c:
        decisions=c.execute("SELECT COUNT(*) n FROM decision_intelligence_records").fetchone()["n"]
        evidence_count=c.execute("SELECT COUNT(*) n FROM decision_evidence_records").fetchone()["n"]
        contribution_count=c.execute("SELECT COUNT(*) n FROM decision_contribution_records").fetchone()["n"]
        timeline_count=c.execute("SELECT COUNT(*) n FROM decision_timeline_records").fetchone()["n"]
    return {"status":"READY","schema_version":SCHEMA_VERSION,"build_version":VERSION,"decision_count":decisions,"evidence_count":evidence_count,"contribution_count":contribution_count,"timeline_event_count":timeline_count,"recommendation_mutation_enabled":False,"confidence_mutation_enabled":False,"future_information_allowed":False,"production_effect":"NONE"}
