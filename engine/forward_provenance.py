"""Forward-only observational producer receipts; never a trade/learning authority.

Receipts are runtime assertions, not independent attestations. Missing/failed
receipts fail closed. No historical row is backfilled or reclassified.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Mapping

from .persistent_store import persistent_sqlite_path

SCHEMA = "apex.forward_provenance.v1"
DEFAULT_DB = persistent_sqlite_path("APEX_FORWARD_PROVENANCE_DB", "apex_forward_provenance.db", migrate_legacy=False)
_LOCK = threading.RLock()
_BOOT = uuid.uuid4().hex
_START_PID = os.getpid()


def enabled() -> bool:
    return os.getenv("APEX_FORWARD_PROVENANCE_ENABLED", "0").lower() in {"1", "true", "yes"}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def runtime_identity() -> dict[str, Any]:
    """Claims only. A deployment verifier must authenticate git_sha separately."""
    release = None
    try:
        manifest = Path(__file__).resolve().parents[1] / "config" / "apex_release_manifest.json"
        release = json.loads(manifest.read_text()).get("apex_version")
    except (OSError, ValueError, TypeError):
        pass
    return {
        "boot_id": _BOOT if os.getpid() == _START_PID else None,
        "pid": os.getpid(),
        "release": release,
        "git_sha_claim": os.getenv("RENDER_GIT_COMMIT") or os.getenv("APEX_GIT_SHA") or None,
        "service_id_claim": os.getenv("RENDER_SERVICE_ID") or None,
        "identity_class": "RUNTIME_CLAIM_UNVERIFIED",
    }


def new_execution_id() -> str:
    return uuid.uuid4().hex


def _canonical(obj: Mapping[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _open(path: str | Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=10000")
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS forward_provenance_events (
      sequence INTEGER PRIMARY KEY AUTOINCREMENT,
      event_id TEXT NOT NULL UNIQUE,
      kind TEXT NOT NULL CHECK(kind IN ('GAMMA_CALCULATED','GAMMA_PERSISTED','DECISION_PERSISTED')),
      entity_id TEXT NOT NULL,
      execution_id TEXT,
      event_time TEXT NOT NULL,
      inserted_at TEXT NOT NULL,
      payload_json TEXT NOT NULL,
      previous_hash TEXT NOT NULL,
      event_hash TEXT NOT NULL UNIQUE
    );
    CREATE INDEX IF NOT EXISTS idx_forward_provenance_entity
      ON forward_provenance_events(kind,entity_id);
    CREATE TRIGGER IF NOT EXISTS forward_provenance_no_update
      BEFORE UPDATE ON forward_provenance_events BEGIN SELECT RAISE(ABORT,'immutable'); END;
    CREATE TRIGGER IF NOT EXISTS forward_provenance_no_delete
      BEFORE DELETE ON forward_provenance_events BEGIN SELECT RAISE(ABORT,'immutable'); END;
    """)
    return c


def append(kind: str, entity_id: str, *, execution_id: str | None = None,
           evidence: Mapping[str, Any] | None = None, path: str | Path | None = None) -> dict[str, Any]:
    """Append within a SQLite transaction. Never promotes authentication."""
    if not enabled():
        return {"status": "DISABLED", "authentication": "UNVERIFIED"}
    if kind not in {'GAMMA_CALCULATED', 'GAMMA_PERSISTED', 'DECISION_PERSISTED'} or not entity_id:
        return {"status": "INVALID_INPUT", "authentication": "UNVERIFIED"}
    claims = runtime_identity()
    if not claims['boot_id']:
        return {"status": "PROCESS_FORK_UNATTESTED", "authentication": "UNVERIFIED"}
    payload = {"schema": SCHEMA, "runtime": claims, "evidence": dict(evidence or {})}
    try:
        with _LOCK:
            c = _open(path or DEFAULT_DB)
            try:
                c.execute("BEGIN IMMEDIATE")
                row = c.execute("SELECT event_hash FROM forward_provenance_events ORDER BY sequence DESC LIMIT 1").fetchone()
                prev = row['event_hash'] if row else 'GENESIS'
                now = utc_now()
                event_id = uuid.uuid4().hex
                body = {"event_id": event_id, "kind": kind, "entity_id": entity_id,
                        "execution_id": execution_id, "event_time": now, "inserted_at": now,
                        "payload": payload, "previous_hash": prev}
                digest = hashlib.sha256(_canonical(body).encode()).hexdigest()
                c.execute("""INSERT INTO forward_provenance_events
                    (event_id,kind,entity_id,execution_id,event_time,inserted_at,payload_json,previous_hash,event_hash)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (event_id,kind,entity_id,execution_id,now,now,_canonical(payload),prev,digest))
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
            finally:
                c.close()
        return {"status": "RECORDED", "event_id": event_id, "event_hash": digest,
                "authentication": "RUNTIME_CLAIM_UNVERIFIED"}
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return {"status": "RECEIPT_WRITE_FAILED", "authentication": "UNVERIFIED"}


def record_calculation(execution_id: str, *, ticker: str, path_version: Any) -> dict[str, Any]:
    return append("GAMMA_CALCULATED", execution_id, execution_id=execution_id,
                  evidence={"ticker": ticker, "path_version": path_version})


def record_gamma(snapshot_id: str, execution_id: str | None, *, inserted: bool,
                 source_timestamp_provenance: Any) -> dict[str, Any]:
    if not inserted or not execution_id:
        return {"status": "NOT_ELIGIBLE", "authentication": "UNVERIFIED"}
    return append("GAMMA_PERSISTED", snapshot_id, execution_id=execution_id,
                  evidence={"source_timestamp_provenance": source_timestamp_provenance})


def record_decision(decision_id: str, gamma_id: str | None, *, inserted: bool,
                    observed_at: str) -> dict[str, Any]:
    if not inserted:
        return {"status": "NOT_ELIGIBLE", "authentication": "UNVERIFIED"}
    # Never infer an execution from matching time or release. Link to an existing
    # gamma receipt only if it was actually captured and the process identity matches.
    execution_id = None
    source_receipt_id = None
    if gamma_id and enabled():
        try:
            c = sqlite3.connect(f"file:{Path(DEFAULT_DB)}?mode=ro", uri=True, timeout=5)
            c.row_factory = sqlite3.Row
            matches = c.execute("""SELECT g.execution_id,g.event_id,g.payload_json,
              (SELECT COUNT(*) FROM forward_provenance_events x
               WHERE x.kind='GAMMA_CALCULATED' AND x.entity_id=g.execution_id
                 AND x.execution_id=g.execution_id) AS calc_count,
              (SELECT x.payload_json FROM forward_provenance_events x
               WHERE x.kind='GAMMA_CALCULATED' AND x.entity_id=g.execution_id
                 AND x.execution_id=g.execution_id LIMIT 1) AS calc_payload
              FROM forward_provenance_events g
              WHERE g.kind='GAMMA_PERSISTED' AND g.entity_id=?""", (gamma_id,)).fetchall()
            c.close()
            if len(matches) == 1 and matches[0]['calc_count'] == 1:
                origin = json.loads(matches[0]['payload_json'])['runtime']
                calc_origin = json.loads(matches[0]['calc_payload'])['runtime']
                current = runtime_identity()
                if (origin['boot_id'] == current['boot_id'] == calc_origin['boot_id']
                        and origin['pid'] == current['pid'] == calc_origin['pid']):
                    execution_id = matches[0]['execution_id']
                    source_receipt_id = matches[0]['event_id']
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
            pass
    return append("DECISION_PERSISTED", decision_id, execution_id=execution_id,
                  evidence={"canonical_gamma_snapshot_id": gamma_id,
                            "gamma_receipt_event_id": source_receipt_id,
                            "decision_observed_at": observed_at,
                            "linkage_class": "SAME_PROCESS_RECEIPT_CLAIM" if source_receipt_id else "UNVERIFIED"})


def verify_chain(*, path: str | Path | None = None) -> dict[str, Any]:
    """Read-only chain check. Chain integrity is NOT independent provenance authentication."""
    target = Path(path or DEFAULT_DB)
    if not target.exists():
        return {"ok": False, "error": "NO_LEDGER", "rows": 0}
    c = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    prev = 'GENESIS'
    count = 0
    try:
        for r in c.execute("SELECT * FROM forward_provenance_events ORDER BY sequence"):
            payload = json.loads(r['payload_json'])
            body = {"event_id": r['event_id'], "kind": r['kind'], "entity_id": r['entity_id'],
                    "execution_id": r['execution_id'], "event_time": r['event_time'],
                    "inserted_at": r['inserted_at'], "payload": payload,
                    "previous_hash": r['previous_hash']}
            if r['previous_hash'] != prev or hashlib.sha256(_canonical(body).encode()).hexdigest() != r['event_hash']:
                return {"ok": False, "error": "HASH_CHAIN_MISMATCH", "sequence": r['sequence'], "rows": count}
            prev = r['event_hash']
            count += 1
    finally:
        c.close()
    return {"ok": True, "rows": count, "head_hash": prev,
            "authentication": "RUNTIME_CLAIM_UNVERIFIED"}
