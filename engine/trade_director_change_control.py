"""APEX Trade Director Phase 27 — Institutional Change Control.

Confirmation-gated, append-only release governance for Trade Director changes.
The engine records proposals, validation evidence, independent reviews, and
release-readiness decisions. It never edits source files, changes runtime
configuration, promotes policy, submits broker orders, or deploys a release.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

VERSION = "PHASE_27"
_ALLOWED_RISK = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
_TERMINAL = {"APPROVED", "REJECTED", "SUPERSEDED"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS apex_change_proposals (
    change_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    phase TEXT NOT NULL,
    change_type TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL,
    target_version TEXT,
    repository_fingerprint TEXT,
    changed_files_json TEXT NOT NULL,
    rollback_plan TEXT NOT NULL,
    compatibility_notes TEXT NOT NULL,
    validation_plan_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    content_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS apex_change_events (
    event_id TEXT PRIMARY KEY,
    change_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    previous_hash TEXT,
    integrity_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_change_status ON apex_change_proposals(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_change_events ON apex_change_events(change_id, occurred_at);
CREATE TRIGGER IF NOT EXISTS apex_change_events_no_update
BEFORE UPDATE ON apex_change_events BEGIN SELECT RAISE(ABORT, 'change events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS apex_change_events_no_delete
BEFORE DELETE ON apex_change_events BEGIN SELECT RAISE(ABORT, 'change events are immutable'); END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def change_control_db_path() -> str:
    configured = os.getenv("APEX_CHANGE_CONTROL_DB", "").strip()
    if configured:
        return configured
    if os.path.isdir("/data") and os.access("/data", os.W_OK):
        return "/data/apex_change_control.db"
    return os.path.join(os.getcwd(), "apex_change_control.db")


def _connect() -> sqlite3.Connection:
    path = change_control_db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    text = value if isinstance(value, str) else _canonical(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json(value: Any, default: Any) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return default


def _proposal(row: sqlite3.Row) -> Dict[str, Any]:
    item = dict(row)
    item["changed_files"] = _json(item.pop("changed_files_json"), [])
    item["validation_plan"] = _json(item.pop("validation_plan_json"), {})
    item["metadata"] = _json(item.pop("metadata_json"), {})
    return item


def _event(row: sqlite3.Row) -> Dict[str, Any]:
    item = dict(row)
    item["payload"] = _json(item.pop("payload_json"), {})
    return item


def _record_event(conn: sqlite3.Connection, change_id: str, event_type: str, actor: str,
                  payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    data = dict(payload or {})
    occurred_at = _now()
    payload_json = _canonical(data)
    payload_hash = _hash(payload_json)
    previous = conn.execute(
        "SELECT integrity_hash FROM apex_change_events WHERE change_id=? ORDER BY occurred_at DESC, rowid DESC LIMIT 1",
        (change_id,),
    ).fetchone()
    previous_hash = previous["integrity_hash"] if previous else ""
    event_id = str(uuid.uuid4())
    integrity_hash = _hash({
        "event_id": event_id, "change_id": change_id, "event_type": event_type,
        "actor": actor, "occurred_at": occurred_at, "payload_hash": payload_hash,
        "previous_hash": previous_hash,
    })
    conn.execute(
        "INSERT INTO apex_change_events VALUES (?,?,?,?,?,?,?,?,?)",
        (event_id, change_id, event_type, actor, occurred_at, payload_json,
         payload_hash, previous_hash, integrity_hash),
    )
    row = conn.execute("SELECT * FROM apex_change_events WHERE event_id=?", (event_id,)).fetchone()
    return _event(row)


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def propose_change(payload: Mapping[str, Any]) -> Dict[str, Any]:
    title = _required_text(payload.get("title"), "title")
    summary = _required_text(payload.get("summary"), "summary")
    phase = _required_text(payload.get("phase") or "27", "phase")
    requested_by = _required_text(payload.get("requested_by"), "requested_by")
    rollback_plan = _required_text(payload.get("rollback_plan"), "rollback_plan")
    compatibility_notes = _required_text(payload.get("compatibility_notes"), "compatibility_notes")
    changed_files = sorted({str(v).strip() for v in (payload.get("changed_files") or []) if str(v).strip()})
    if not changed_files:
        raise ValueError("changed_files must contain at least one path")
    risk_level = str(payload.get("risk_level") or "MEDIUM").upper()
    if risk_level not in _ALLOWED_RISK:
        raise ValueError("risk_level must be LOW, MEDIUM, HIGH, or CRITICAL")
    validation_plan = dict(payload.get("validation_plan") or {})
    metadata = dict(payload.get("metadata") or {})
    now = _now()
    normalized = {
        "title": title, "summary": summary, "phase": phase,
        "change_type": str(payload.get("change_type") or "FEATURE").upper(),
        "risk_level": risk_level, "requested_by": requested_by,
        "target_version": str(payload.get("target_version") or ""),
        "repository_fingerprint": str(payload.get("repository_fingerprint") or ""),
        "changed_files": changed_files, "rollback_plan": rollback_plan,
        "compatibility_notes": compatibility_notes, "validation_plan": validation_plan,
        "metadata": metadata,
    }
    change_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "apex-change:" + _hash(normalized)))
    content_hash = _hash(normalized)
    with _connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO apex_change_proposals
            (change_id,title,summary,phase,change_type,risk_level,requested_by,created_at,updated_at,status,
             target_version,repository_fingerprint,changed_files_json,rollback_plan,compatibility_notes,
             validation_plan_json,metadata_json,content_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (change_id, title, summary, phase, normalized["change_type"], risk_level, requested_by,
             now, now, "DRAFT", normalized["target_version"], normalized["repository_fingerprint"],
             _canonical(changed_files), rollback_plan, compatibility_notes, _canonical(validation_plan),
             _canonical(metadata), content_hash),
        )
        exists = conn.execute("SELECT COUNT(*) c FROM apex_change_events WHERE change_id=?", (change_id,)).fetchone()["c"]
        if not exists:
            _record_event(conn, change_id, "PROPOSED", requested_by, {"content_hash": content_hash})
        row = conn.execute("SELECT * FROM apex_change_proposals WHERE change_id=?", (change_id,)).fetchone()
    return _proposal(row)


def get_change(change_id: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM apex_change_proposals WHERE change_id=?", (change_id,)).fetchone()
        if not row:
            return None
        item = _proposal(row)
        events = conn.execute("SELECT * FROM apex_change_events WHERE change_id=? ORDER BY occurred_at", (change_id,)).fetchall()
    item["events"] = [_event(e) for e in events]
    return item


def change_history(limit: int = 100, status: Optional[str] = None) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 100), 1000))
    with _connect() as conn:
        if status:
            rows = conn.execute("SELECT * FROM apex_change_proposals WHERE status=? ORDER BY updated_at DESC LIMIT ?",
                                (str(status).upper(), limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM apex_change_proposals ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    return [_proposal(r) for r in rows]


def validate_change(change_id: str, evidence: Mapping[str, Any], actor: str) -> Dict[str, Any]:
    actor = _required_text(actor, "actor")
    required = ("python_compilation", "regression_tests", "api_validation", "dashboard_validation", "zip_integrity")
    normalized = {key: bool(evidence.get(key)) for key in required}
    normalized["test_total"] = max(0, int(evidence.get("test_total") or 0))
    normalized["test_failures"] = max(0, int(evidence.get("test_failures") or 0))
    normalized["notes"] = str(evidence.get("notes") or "")
    passed = all(normalized[key] for key in required) and normalized["test_failures"] == 0
    normalized["passed"] = passed
    with _connect() as conn:
        row = conn.execute("SELECT * FROM apex_change_proposals WHERE change_id=?", (change_id,)).fetchone()
        if not row:
            raise KeyError("change not found")
        if row["status"] in _TERMINAL:
            raise ValueError(f"cannot validate terminal change in {row['status']} state")
        status = "AWAITING_APPROVAL" if passed else "VALIDATION_FAILED"
        conn.execute("UPDATE apex_change_proposals SET status=?, updated_at=? WHERE change_id=?", (status, _now(), change_id))
        _record_event(conn, change_id, "VALIDATED" if passed else "VALIDATION_FAILED", actor, normalized)
    return get_change(change_id) or {}


def review_change(change_id: str, decision: str, reviewer: str, reason: str) -> Dict[str, Any]:
    reviewer = _required_text(reviewer, "reviewer")
    reason = _required_text(reason, "reason")
    decision = str(decision or "").upper()
    if decision not in {"APPROVE", "REJECT"}:
        raise ValueError("decision must be APPROVE or REJECT")
    with _connect() as conn:
        row = conn.execute("SELECT * FROM apex_change_proposals WHERE change_id=?", (change_id,)).fetchone()
        if not row:
            raise KeyError("change not found")
        if row["status"] in _TERMINAL:
            raise ValueError(f"change is already {row['status']}")
        if reviewer == row["requested_by"]:
            raise ValueError("independent reviewer required")
        if decision == "APPROVE" and row["status"] != "AWAITING_APPROVAL":
            raise ValueError("change must pass validation before approval")
        status = "APPROVED" if decision == "APPROVE" else "REJECTED"
        conn.execute("UPDATE apex_change_proposals SET status=?, updated_at=? WHERE change_id=?", (status, _now(), change_id))
        _record_event(conn, change_id, status, reviewer, {"reason": reason})
    return get_change(change_id) or {}


def verify_change_integrity(change_id: Optional[str] = None) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    with _connect() as conn:
        if change_id:
            rows = conn.execute("SELECT * FROM apex_change_events WHERE change_id=? ORDER BY occurred_at, rowid", (change_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM apex_change_events ORDER BY change_id, occurred_at, rowid").fetchall()
    previous_by_change: Dict[str, str] = {}
    for row in rows:
        expected_payload = _hash(row["payload_json"])
        expected_previous = previous_by_change.get(row["change_id"], "")
        expected_integrity = _hash({
            "event_id": row["event_id"], "change_id": row["change_id"], "event_type": row["event_type"],
            "actor": row["actor"], "occurred_at": row["occurred_at"], "payload_hash": row["payload_hash"],
            "previous_hash": row["previous_hash"] or "",
        })
        if row["payload_hash"] != expected_payload:
            findings.append({"severity": "CRITICAL", "type": "PAYLOAD_HASH_MISMATCH", "event_id": row["event_id"]})
        if (row["previous_hash"] or "") != expected_previous:
            findings.append({"severity": "CRITICAL", "type": "CHAIN_BREAK", "event_id": row["event_id"]})
        if row["integrity_hash"] != expected_integrity:
            findings.append({"severity": "CRITICAL", "type": "INTEGRITY_HASH_MISMATCH", "event_id": row["event_id"]})
        previous_by_change[row["change_id"]] = row["integrity_hash"]
    return {
        "status": "VERIFIED" if not findings else "TAMPER_DETECTED",
        "score": 100.0 if not findings else max(0.0, 100.0 - len(findings) * 25.0),
        "event_count": len(rows), "finding_count": len(findings), "findings": findings,
        "checked_at": _now(),
    }


def build_change_control(context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    ctx = dict(context or {})
    history = change_history(100)
    counts = {state: 0 for state in ("DRAFT", "VALIDATION_FAILED", "AWAITING_APPROVAL", "APPROVED", "REJECTED")}
    for item in history:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    pending = [item for item in history if item["status"] not in _TERMINAL]
    integrity = verify_change_integrity()
    upstream = ctx.get("institutional_command_center") if isinstance(ctx.get("institutional_command_center"), Mapping) else {}
    system_state = str(upstream.get("system_state") or "UNKNOWN")
    release_state = "HOLD"
    if integrity["status"] != "VERIFIED":
        release_state = "INTEGRITY_BLOCKED"
    elif counts.get("AWAITING_APPROVAL"):
        release_state = "REVIEW_REQUIRED"
    elif counts.get("APPROVED") and not pending:
        release_state = "APPROVED_CHANGES_AVAILABLE"
    return {
        "version": VERSION,
        "as_of": _now(),
        "change_control_state": release_state,
        "system_state_observed": system_state,
        "proposal_count": len(history),
        "pending_count": len(pending),
        "status_counts": counts,
        "latest_changes": history[:10],
        "integrity": integrity,
        "controls": {
            "independent_review_required": True,
            "validation_required_before_approval": True,
            "append_only_audit_events": True,
            "automatic_deployment": False,
            "runtime_mutation": False,
            "broker_access": False,
            "autonomous_execution": False,
        },
        "safety_note": "Phase 27 records and approves change intent only. Deployment and live trading remain separately confirmation-gated.",
    }
