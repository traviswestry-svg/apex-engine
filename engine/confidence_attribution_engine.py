"""APEX 14 Sprint 10.2: deterministic Confidence Attribution Engine.

This module classifies and reconciles contribution records captured by Sprint 10.1.
It never recalculates or mutates the canonical confidence score.
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

VERSION = "14.0.10.2"
SCHEMA_VERSION = "apex.confidence_attribution_analysis.v1"


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
    core.init_db()
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS confidence_attribution_analyses(
          attribution_id TEXT PRIMARY KEY,
          decision_id TEXT NOT NULL UNIQUE,
          explainability_id TEXT NOT NULL,
          canonical_confidence REAL,
          deterministic_total REAL NOT NULL,
          positive_total REAL NOT NULL,
          negative_total REAL NOT NULL,
          neutral_total REAL NOT NULL,
          unknown_total REAL NOT NULL,
          contributor_count INTEGER NOT NULL,
          reconciliation_status TEXT NOT NULL,
          analysis_json TEXT NOT NULL,
          schema_version TEXT NOT NULL,
          engine_version TEXT NOT NULL,
          integrity_hash TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(decision_id) REFERENCES decision_intelligence_records(decision_id)
        );
        CREATE INDEX IF NOT EXISTS idx_conf_attr_created ON confidence_attribution_analyses(created_at);
        """)
    return {"ok": True, "schema_version": SCHEMA_VERSION, "build_version": VERSION}


def _bucket(value: float) -> str:
    if value > 0:
        return "POSITIVE"
    if value < 0:
        return "NEGATIVE"
    return "NEUTRAL"


def _resolve(identifier: str) -> dict[str, Any] | None:
    return core.get(identifier)


def _build(record: dict[str, Any]) -> dict[str, Any]:
    rows = []
    totals = {"POSITIVE": 0.0, "NEGATIVE": 0.0, "NEUTRAL": 0.0, "UNKNOWN": 0.0}
    for item in record.get("contributions") or []:
        try:
            value = float(item.get("contribution"))
            bucket = _bucket(value)
        except (TypeError, ValueError):
            value = 0.0
            bucket = "UNKNOWN"
        totals[bucket] = round(totals[bucket] + value, 10)
        rows.append({
            "contribution_id": item.get("contribution_id"),
            "contributor": item.get("contributor") or "UNKNOWN",
            "source_direction": item.get("direction") or "NEUTRAL",
            "classification": bucket,
            "contribution": value,
            "absolute_contribution": abs(value),
            "reliability": item.get("reliability"),
            "freshness": item.get("freshness"),
            "explanation": item.get("explanation") or "",
            "integrity_hash": item.get("integrity_hash"),
        })
    rows.sort(key=lambda x: (-x["absolute_contribution"], str(x["contributor"])))
    deterministic_total = round(sum(float(x["contribution"]) for x in rows), 10)
    canonical_total = (((record.get("decision") or {}).get("confidence_attribution") or {}).get("deterministic_total"))
    try:
        canonical_total = float(canonical_total)
    except (TypeError, ValueError):
        canonical_total = None
    delta = None if canonical_total is None else round(deterministic_total - canonical_total, 10)
    reconciliation = "UNAVAILABLE" if canonical_total is None else ("RECONCILED" if abs(delta or 0.0) < 1e-9 else "MISMATCH")
    confidence = record.get("confidence")
    return {
        "decision_id": record["decision_id"],
        "recommendation_id": record["recommendation_id"],
        "explainability_id": record["explainability_id"],
        "canonical_confidence": confidence,
        "deterministic_total": deterministic_total,
        "canonical_contribution_total": canonical_total,
        "reconciliation_delta": delta,
        "reconciliation_status": reconciliation,
        "totals": {
            "positive": round(totals["POSITIVE"], 10),
            "negative": round(totals["NEGATIVE"], 10),
            "neutral": round(totals["NEUTRAL"], 10),
            "unknown": round(totals["UNKNOWN"], 10),
        },
        "contributors": rows,
        "strongest_support": next((x for x in rows if x["classification"] == "POSITIVE"), None),
        "strongest_conflict": next((x for x in rows if x["classification"] == "NEGATIVE"), None),
        "limitations": [
            "Canonical confidence is displayed but never recalculated",
            "Attribution uses only immutable Sprint 10.1 contribution records",
            "Zero-value contributions are classified as neutral",
            "Missing or malformed contributions are classified as unknown",
            "No future outcomes or post-hoc explanations are used",
        ],
        "confidence_mutation_enabled": False,
        "production_effect": "NONE",
    }


def analyze(identifier: str, *, actor: str = "SYSTEM") -> dict[str, Any]:
    init_db()
    record = _resolve(identifier)
    if record is None:
        return {"ok": False, "status": "UNAVAILABLE", "error": "decision_not_found"}
    with _conn() as c:
        existing = c.execute("SELECT * FROM confidence_attribution_analyses WHERE decision_id=?", (record["decision_id"],)).fetchone()
    if existing:
        payload = _load(existing["analysis_json"])
        return {"ok": True, "status": "IMMUTABLE_EXISTS", "created": False, "attribution_id": existing["attribution_id"], "integrity_hash": existing["integrity_hash"], "analysis": payload}
    payload = _build(record)
    attribution_id = str(uuid.uuid4())
    created_at = _now()
    identity = {"attribution_id": attribution_id, "decision_id": record["decision_id"], "analysis": payload, "schema_version": SCHEMA_VERSION}
    integrity_hash = hashlib.sha256(_json(identity).encode()).hexdigest()
    t = payload["totals"]
    with _conn() as c:
        c.execute("INSERT INTO confidence_attribution_analyses VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            attribution_id, record["decision_id"], record["explainability_id"], payload.get("canonical_confidence"),
            payload["deterministic_total"], t["positive"], t["negative"], t["neutral"], t["unknown"],
            len(payload["contributors"]), payload["reconciliation_status"], _json(payload), SCHEMA_VERSION, VERSION,
            integrity_hash, created_at,
        ))
    gov.audit("CREATE_CONFIDENCE_ATTRIBUTION", "confidence_attribution", attribution_id,
              new={"decision_id": record["decision_id"], "integrity_hash": integrity_hash}, actor=actor,
              explanation="Immutable confidence attribution analysis created from preserved contributions")
    return {"ok": True, "status": "CREATED", "created": True, "attribution_id": attribution_id, "integrity_hash": integrity_hash, "analysis": payload}


def get(identifier: str) -> dict[str, Any] | None:
    init_db()
    record = _resolve(identifier)
    if record is None:
        return None
    with _conn() as c:
        row = c.execute("SELECT * FROM confidence_attribution_analyses WHERE decision_id=?", (record["decision_id"],)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["analysis"] = _load(out.pop("analysis_json"))
    return out


def explain(identifier: str) -> dict[str, Any]:
    existing = get(identifier)
    if existing:
        return {"ok": True, "status": "READY", **existing["analysis"], "attribution_id": existing["attribution_id"], "integrity_hash": existing["integrity_hash"]}
    result = analyze(identifier)
    if not result.get("ok"):
        return result
    return {"ok": True, "status": "READY", **result["analysis"], "attribution_id": result["attribution_id"], "integrity_hash": result["integrity_hash"]}


def list_analyses(limit: int = 100) -> list[dict[str, Any]]:
    init_db()
    with _conn() as c:
        rows = c.execute("SELECT attribution_id,decision_id,explainability_id,canonical_confidence,deterministic_total,positive_total,negative_total,neutral_total,unknown_total,contributor_count,reconciliation_status,integrity_hash,created_at FROM confidence_attribution_analyses ORDER BY created_at DESC LIMIT ?", (max(1, min(int(limit), 1000)),)).fetchall()
    return [dict(r) for r in rows]


def status() -> dict[str, Any]:
    init_db()
    with _conn() as c:
        count = c.execute("SELECT COUNT(*) n FROM confidence_attribution_analyses").fetchone()["n"]
        mismatches = c.execute("SELECT COUNT(*) n FROM confidence_attribution_analyses WHERE reconciliation_status='MISMATCH'").fetchone()["n"]
    return {
        "status": "READY", "schema_version": SCHEMA_VERSION, "build_version": VERSION,
        "analysis_count": count, "reconciliation_mismatch_count": mismatches,
        "confidence_recalculation_enabled": False, "confidence_mutation_enabled": False,
        "future_information_allowed": False, "production_effect": "NONE",
    }
