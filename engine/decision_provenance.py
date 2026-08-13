"""Immutable decision provenance snapshots and deterministic replay checks."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import threading
from copy import deepcopy
from typing import Any, Dict, Optional

STORE_VERSION = "10.0.0_DECISION_PROVENANCE"
_DB_PATH = os.getenv("DB_PATH", "apex_tracking.db")
_LOCK = threading.Lock()
_READY = False


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


def init_db() -> bool:
    global _READY
    try:
        folder = os.path.dirname(_DB_PATH)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with sqlite3.connect(_DB_PATH, timeout=10) as c:
            c.execute("""CREATE TABLE IF NOT EXISTS decision_provenance (
                snapshot_id TEXT PRIMARY KEY,
                sample_id TEXT UNIQUE NOT NULL,
                decision_time TEXT NOT NULL,
                ticker TEXT,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                written_at TEXT NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_dp_time ON decision_provenance(decision_time)")
            c.commit()
        _READY = True
    except Exception:
        _READY = False
    return _READY


def is_ready() -> bool:
    return _READY


def build_snapshot(*, sample_id: str, decision_time: str, ticker: str,
                   raw_inputs: Dict[str, Any], normalized_inputs: Dict[str, Any],
                   quality_assessments: Dict[str, Any], feature_vector: Dict[str, Any],
                   decision_output: Optional[Dict[str, Any]] = None,
                   model_versions: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = {
        "sample_id": sample_id, "decision_time": decision_time, "ticker": ticker,
        "raw_inputs": deepcopy(raw_inputs or {}),
        "normalized_inputs": deepcopy(normalized_inputs or {}),
        "quality_assessments": deepcopy(quality_assessments or {}),
        "feature_vector": deepcopy(feature_vector or {}),
        "decision_output": deepcopy(decision_output or {}),
        "model_versions": deepcopy(model_versions or {}),
        "provenance_version": STORE_VERSION,
    }
    ph = content_hash(payload)
    return {"snapshot_id": f"dp_{ph[:24]}", "payload_hash": ph, "payload": payload,
            "schema_version": STORE_VERSION}


def write_snapshot(snapshot: Dict[str, Any]) -> bool:
    if not _READY or not snapshot:
        return False
    p = snapshot["payload"]
    try:
        with _LOCK, sqlite3.connect(_DB_PATH, timeout=10) as c:
            exists = c.execute("SELECT 1 FROM decision_provenance WHERE sample_id=?",
                               (p["sample_id"],)).fetchone()
            if exists:
                return False
            c.execute("""INSERT INTO decision_provenance
                (snapshot_id,sample_id,decision_time,ticker,payload_json,payload_hash,schema_version,written_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (snapshot["snapshot_id"], p["sample_id"], p["decision_time"], p.get("ticker"),
                 _canonical(p), snapshot["payload_hash"], snapshot["schema_version"],
                 dt.datetime.now(dt.timezone.utc).isoformat()))
            c.commit()
        return True
    except Exception:
        return False


def get_snapshot(sample_id: str) -> Optional[Dict[str, Any]]:
    if not _READY:
        return None
    try:
        with sqlite3.connect(_DB_PATH, timeout=10) as c:
            c.row_factory = sqlite3.Row
            r = c.execute("SELECT * FROM decision_provenance WHERE sample_id=?", (sample_id,)).fetchone()
        if not r:
            return None
        payload = json.loads(r["payload_json"])
        return {"snapshot_id": r["snapshot_id"], "sample_id": r["sample_id"],
                "decision_time": r["decision_time"], "ticker": r["ticker"],
                "payload_hash": r["payload_hash"], "schema_version": r["schema_version"],
                "payload": payload, "integrity_ok": content_hash(payload) == r["payload_hash"]}
    except Exception:
        return None


def verify_replay(sample_id: str, regenerated_payload: Dict[str, Any]) -> Dict[str, Any]:
    stored = get_snapshot(sample_id)
    if not stored:
        return {"available": False, "match": False, "reason": "snapshot not found"}
    actual = content_hash(regenerated_payload)
    return {"available": True, "match": actual == stored["payload_hash"],
            "stored_hash": stored["payload_hash"], "regenerated_hash": actual,
            "integrity_ok": stored["integrity_ok"]}
