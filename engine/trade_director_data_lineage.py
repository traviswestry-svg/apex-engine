"""APEX Trade Director Phase 28 — Institutional Data Integrity & Lineage.

Append-only provenance and integrity layer for the coordinated Trade Director stack.
The module records normalized evidence lineage, validates parent chains and hashes,
and exposes read-only audit views. It never changes strategy, risk, authorization,
execution, lifecycle, learning, governance, or broker state.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from engine.trade_director_lifecycle_contracts import as_mapping, utc_now_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS apex_lineage_events (
    lineage_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    trade_id TEXT,
    phase TEXT,
    engine_name TEXT,
    engine_version TEXT,
    source_system TEXT,
    dataset_version TEXT,
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    confidence REAL,
    validation_status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    previous_hash TEXT,
    integrity_hash TEXT NOT NULL,
    UNIQUE(event_type, entity_id, payload_hash)
);
CREATE TABLE IF NOT EXISTS apex_lineage_relationships (
    relationship_id TEXT PRIMARY KEY,
    parent_lineage_id TEXT NOT NULL,
    child_lineage_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(parent_lineage_id, child_lineage_id, relationship_type)
);
CREATE TABLE IF NOT EXISTS apex_integrity_checks (
    check_id TEXT PRIMARY KEY,
    checked_at TEXT NOT NULL,
    scope TEXT NOT NULL,
    status TEXT NOT NULL,
    score REAL NOT NULL,
    findings_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS apex_dataset_versions (
    dataset_name TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    source_system TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    content_hash TEXT,
    PRIMARY KEY(dataset_name, dataset_version)
);
CREATE TABLE IF NOT EXISTS apex_engine_versions (
    engine_name TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    phase TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    content_hash TEXT,
    PRIMARY KEY(engine_name, engine_version)
);
CREATE INDEX IF NOT EXISTS idx_lineage_trade ON apex_lineage_events(trade_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_lineage_entity ON apex_lineage_events(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_lineage_phase ON apex_lineage_events(phase, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_lineage_parent ON apex_lineage_relationships(parent_lineage_id);
CREATE INDEX IF NOT EXISTS idx_lineage_child ON apex_lineage_relationships(child_lineage_id);
CREATE TRIGGER IF NOT EXISTS apex_lineage_events_no_update
BEFORE UPDATE ON apex_lineage_events BEGIN SELECT RAISE(ABORT, 'lineage events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS apex_lineage_events_no_delete
BEFORE DELETE ON apex_lineage_events BEGIN SELECT RAISE(ABORT, 'lineage events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS apex_lineage_relationships_no_update
BEFORE UPDATE ON apex_lineage_relationships BEGIN SELECT RAISE(ABORT, 'lineage relationships are immutable'); END;
CREATE TRIGGER IF NOT EXISTS apex_lineage_relationships_no_delete
BEFORE DELETE ON apex_lineage_relationships BEGIN SELECT RAISE(ABORT, 'lineage relationships are immutable'); END;
"""

_PHASE_SPECS = [
    ("11", "session_intelligence", "Session Intelligence"),
    ("12", "market_memory", "Market Memory"),
    ("13", "cross_asset_intelligence", "Cross-Asset Intelligence"),
    ("14", "strategy_orchestration", "Strategy Orchestration"),
    ("15", "options_intelligence", "Options Intelligence"),
    ("16", "execution_desk", "Execution Desk"),
    ("17", "multi_timeframe_intelligence", "Multi-Timeframe Intelligence"),
    ("18", "flow_intelligence", "Institutional Flow"),
    ("19", "decision_intelligence", "Decision Committee"),
    ("20", "institutional_decision_engine", "Authorization"),
    ("21", "trade_lifecycle", "Trade Lifecycle"),
    ("22", "institutional_learning", "Institutional Learning"),
    ("23", "replay_laboratory", "Replay Laboratory"),
    ("24", "policy_governance", "Policy Governance"),
    ("25", "shadow_validation", "Shadow Validation"),
    ("26", "institutional_command_center", "Performance Command Center"),
    ("27", "change_control", "Change Control"),
]


def lineage_db_path() -> str:
    configured = os.getenv("APEX_LINEAGE_DB", "").strip()
    if configured:
        return configured
    if os.path.isdir("/data") and os.access("/data", os.W_OK):
        return "/data/apex_data_lineage.db"
    return os.path.join(os.getcwd(), "apex_data_lineage.db")


def _connect() -> sqlite3.Connection:
    path = lineage_db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


def _canonical(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    text = value if isinstance(value, str) else _canonical(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _confidence(payload: Mapping[str, Any]) -> Optional[float]:
    for key in ("confidence", "score", "health_score", "overall_score"):
        try:
            value = float(payload.get(key))
            return round(value * 100.0 if 0 < value <= 1 else value, 2)
        except (TypeError, ValueError):
            continue
    return None


def _version(payload: Mapping[str, Any], phase: str) -> str:
    return str(payload.get("version") or payload.get("engine_version") or f"PHASE_{phase}")


def _event_dict(row: sqlite3.Row) -> Dict[str, Any]:
    item = dict(row)
    try:
        item["payload"] = json.loads(item.pop("payload_json"))
    except Exception:
        item["payload"] = {}
        item.pop("payload_json", None)
    return item


def record_lineage_event(
    payload: Mapping[str, Any], *, event_type: str, entity_type: str = "ENGINE_OUTPUT",
    entity_id: Optional[str] = None, trade_id: Optional[str] = None, phase: str = "",
    engine_name: str = "", engine_version: str = "", source_system: str = "APEX",
    dataset_version: str = "", parent_ids: Optional[Sequence[str]] = None,
    relationship_type: str = "DERIVED_FROM", occurred_at: Optional[str] = None,
) -> Dict[str, Any]:
    data = dict(payload or {})
    payload_json = _canonical(data)
    payload_hash = _hash(payload_json)
    entity_id = str(entity_id or data.get("trade_id") or data.get("id") or f"{phase}:{payload_hash[:16]}")
    trade_id = str(trade_id or data.get("trade_id") or as_mapping(data.get("position")).get("trade_id") or "") or None
    now = utc_now_iso()
    occurred = str(occurred_at or data.get("as_of") or data.get("checked_at") or data.get("updated_at") or now)
    lineage_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"apex:{event_type}:{entity_id}:{payload_hash}"))
    with _connect() as conn:
        previous = conn.execute("SELECT integrity_hash FROM apex_lineage_events ORDER BY recorded_at DESC, rowid DESC LIMIT 1").fetchone()
        previous_hash = previous["integrity_hash"] if previous else ""
        integrity_hash = _hash({"lineage_id": lineage_id, "payload_hash": payload_hash, "previous_hash": previous_hash,
                                "occurred_at": occurred, "event_type": event_type, "entity_id": entity_id})
        conn.execute(
            """INSERT OR IGNORE INTO apex_lineage_events
            (lineage_id,event_type,entity_type,entity_id,trade_id,phase,engine_name,engine_version,source_system,dataset_version,
             occurred_at,recorded_at,confidence,validation_status,payload_json,payload_hash,previous_hash,integrity_hash)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (lineage_id, event_type, entity_type, entity_id, trade_id, phase, engine_name, engine_version,
             source_system, dataset_version, occurred, now, _confidence(data), "VERIFIED", payload_json,
             payload_hash, previous_hash, integrity_hash),
        )
        for parent_id in dict.fromkeys(parent_ids or []):
            if not parent_id or parent_id == lineage_id:
                continue
            rel_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"apex-rel:{parent_id}:{lineage_id}:{relationship_type}"))
            conn.execute("INSERT OR IGNORE INTO apex_lineage_relationships VALUES (?,?,?,?,?)",
                         (rel_id, parent_id, lineage_id, relationship_type, now))
        if dataset_version:
            conn.execute("""INSERT INTO apex_dataset_versions VALUES (?,?,?,?,?,?)
                ON CONFLICT(dataset_name,dataset_version) DO UPDATE SET last_seen_at=excluded.last_seen_at""",
                (source_system, dataset_version, source_system, now, now, payload_hash))
        if engine_name and engine_version:
            conn.execute("""INSERT INTO apex_engine_versions VALUES (?,?,?,?,?,?)
                ON CONFLICT(engine_name,engine_version) DO UPDATE SET last_seen_at=excluded.last_seen_at""",
                (engine_name, engine_version, phase, now, now, payload_hash))
        row = conn.execute("SELECT * FROM apex_lineage_events WHERE lineage_id=?", (lineage_id,)).fetchone()
    return _event_dict(row)


def lineage_history(limit: int = 100, trade_id: Optional[str] = None) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 100), 1000))
    with _connect() as conn:
        if trade_id:
            rows = conn.execute("SELECT * FROM apex_lineage_events WHERE trade_id=? ORDER BY occurred_at DESC LIMIT ?", (trade_id, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM apex_lineage_events ORDER BY recorded_at DESC LIMIT ?", (limit,)).fetchall()
    return [_event_dict(r) for r in rows]


def get_lineage_event(lineage_id: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM apex_lineage_events WHERE lineage_id=?", (lineage_id,)).fetchone()
    return _event_dict(row) if row else None


def lineage_tree(trade_id: str) -> Dict[str, Any]:
    nodes = lineage_history(1000, trade_id)
    ids = {n["lineage_id"] for n in nodes}
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM apex_lineage_relationships").fetchall()
    edges = [dict(r) for r in rows if r["parent_lineage_id"] in ids and r["child_lineage_id"] in ids]
    return {"trade_id": trade_id, "node_count": len(nodes), "edge_count": len(edges), "nodes": nodes, "edges": edges}


def verify_integrity(scope: str = "ALL") -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    with _connect() as conn:
        events = conn.execute("SELECT * FROM apex_lineage_events ORDER BY recorded_at, rowid").fetchall()
        relationships = conn.execute("SELECT * FROM apex_lineage_relationships").fetchall()
        ids = {r["lineage_id"] for r in events}
        for row in events:
            expected_payload = _hash(row["payload_json"])
            if expected_payload != row["payload_hash"]:
                findings.append({"type": "PAYLOAD_HASH_MISMATCH", "severity": "CRITICAL", "lineage_id": row["lineage_id"]})
            expected_integrity = _hash({"lineage_id": row["lineage_id"], "payload_hash": row["payload_hash"],
                                        "previous_hash": row["previous_hash"] or "", "occurred_at": row["occurred_at"],
                                        "event_type": row["event_type"], "entity_id": row["entity_id"]})
            if expected_integrity != row["integrity_hash"]:
                findings.append({"type": "INTEGRITY_HASH_MISMATCH", "severity": "CRITICAL", "lineage_id": row["lineage_id"]})
        for rel in relationships:
            if rel["parent_lineage_id"] not in ids:
                findings.append({"type": "MISSING_PARENT", "severity": "ERROR", "lineage_id": rel["child_lineage_id"], "parent_id": rel["parent_lineage_id"]})
            if rel["child_lineage_id"] not in ids:
                findings.append({"type": "MISSING_CHILD", "severity": "ERROR", "lineage_id": rel["child_lineage_id"]})
        critical = sum(f["severity"] == "CRITICAL" for f in findings)
        errors = sum(f["severity"] == "ERROR" for f in findings)
        warnings = sum(f["severity"] == "WARNING" for f in findings)
        status = "TAMPER_DETECTED" if critical else "FAILED" if errors else "WARNING" if warnings else "VERIFIED"
        score = max(0.0, 100.0 - critical * 35.0 - errors * 15.0 - warnings * 5.0)
        result = {"version": "PHASE_28", "checked_at": utc_now_iso(), "scope": scope, "status": status,
                  "integrity_score": round(score, 1), "event_count": len(events), "relationship_count": len(relationships),
                  "critical_count": critical, "error_count": errors, "warning_count": warnings, "findings": findings}
        conn.execute("INSERT INTO apex_integrity_checks VALUES (?,?,?,?,?,?)",
                     (str(uuid.uuid4()), result["checked_at"], scope, status, score, _canonical(findings)))
    return result


def build_data_lineage(context: Optional[Mapping[str, Any]] = None, *, persist: bool = True) -> Dict[str, Any]:
    ctx = dict(context or {})
    trade_id = str(ctx.get("trade_id") or as_mapping(ctx.get("position")).get("trade_id") or as_mapping(ctx.get("position")).get("id") or "") or None
    parent_ids: List[str] = []
    recorded: List[Dict[str, Any]] = []
    available = 0
    for phase, key, name in _PHASE_SPECS:
        payload = as_mapping(ctx.get(key))
        if not payload:
            continue
        available += 1
        if persist:
            event = record_lineage_event(payload, event_type="ENGINE_OUTPUT", entity_type="TRADE_DIRECTOR_PHASE",
                entity_id=f"{trade_id or 'SYSTEM'}:{phase}:{_hash(payload)[:16]}", trade_id=trade_id, phase=phase,
                engine_name=name, engine_version=_version(payload, phase), source_system=str(payload.get("source") or "APEX"),
                dataset_version=str(payload.get("dataset_version") or payload.get("data_version") or ""), parent_ids=parent_ids[-3:])
            recorded.append(event)
            parent_ids.append(event["lineage_id"])
    integrity = verify_integrity("TRADE:" + trade_id if trade_id else "SYSTEM")
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM apex_lineage_events").fetchone()["c"]
        versions = [dict(r) for r in conn.execute("SELECT * FROM apex_engine_versions ORDER BY last_seen_at DESC LIMIT 30").fetchall()]
        datasets = [dict(r) for r in conn.execute("SELECT * FROM apex_dataset_versions ORDER BY last_seen_at DESC LIMIT 30").fetchall()]
    coverage = round(available / len(_PHASE_SPECS) * 100.0, 1)
    return {
        "version": "PHASE_28", "as_of": utc_now_iso(), "mode": "INSTITUTIONAL_DATA_INTEGRITY_AND_LINEAGE",
        "lineage_state": integrity["status"], "lineage_coverage_pct": coverage, "phases_with_evidence": available,
        "phases_expected": len(_PHASE_SPECS), "events_recorded_this_run": len(recorded), "total_lineage_events": total,
        "latest_events": recorded[-10:] if recorded else lineage_history(10, trade_id), "integrity": integrity,
        "engine_versions": versions, "dataset_versions": datasets,
        "controls": {"append_only": True, "immutable_events": True, "read_only_audit": True, "broker_access": False,
                     "order_submission": False, "risk_mutation": False, "policy_mutation": False},
        "safety_note": "Phase 28 is an append-only audit and provenance layer. It cannot modify trading decisions, authorization, risk, lifecycle management, policies, or broker orders.",
    }


def export_lineage(trade_id: Optional[str] = None) -> Dict[str, Any]:
    events = lineage_history(1000, trade_id)
    return {"version": "PHASE_28", "exported_at": utc_now_iso(), "trade_id": trade_id,
            "events": events, "integrity": verify_integrity("EXPORT"), "event_count": len(events)}
