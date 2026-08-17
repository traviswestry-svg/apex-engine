"""APEX 67.1.0 — Silent-Degradation Observability.

Captures non-fatal fallbacks and swallowed exceptions as structured evidence.
Recording is best-effort and must never become a new failure source.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "67.1.0"
SCHEMA_VERSION = "apex.silent_degradation_observability.v1"
DEFAULT_DB = os.getenv("APEX_DEGRADATION_DB", "apex_degradation_events.db")
_MAX_MEMORY = int(os.getenv("APEX_DEGRADATION_MEMORY_EVENTS", "500"))

_LOCK = threading.RLock()
_MEMORY: deque[dict[str, Any]] = deque(maxlen=max(50, _MAX_MEMORY))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(component: str, operation: str, exception_type: str, fallback: str) -> str:
    raw = f"{component}|{operation}|{exception_type}|{fallback}".encode("utf-8", "replace")
    return hashlib.sha256(raw).hexdigest()[:20]


def _connect(path: str | Path = DEFAULT_DB):
    from .canonical_persistence import connect
    c = connect(path)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS degradation_events(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      fingerprint TEXT NOT NULL,
      first_seen TEXT NOT NULL,
      last_seen TEXT NOT NULL,
      component TEXT NOT NULL,
      operation TEXT NOT NULL,
      severity TEXT NOT NULL,
      exception_type TEXT,
      message TEXT,
      fallback TEXT,
      decision_authority_suppressed INTEGER NOT NULL DEFAULT 0,
      source TEXT,
      context_json TEXT,
      occurrence_count INTEGER NOT NULL DEFAULT 1
    );
    CREATE UNIQUE INDEX IF NOT EXISTS ux_degradation_fingerprint
      ON degradation_events(fingerprint);
    CREATE INDEX IF NOT EXISTS idx_degradation_last_seen
      ON degradation_events(last_seen DESC);
    """)
    return c


def record_degradation(
    *,
    component: str,
    operation: str,
    exc: BaseException | None = None,
    severity: str = "DEGRADED",
    fallback: str = "UNKNOWN",
    decision_authority_suppressed: bool = False,
    source: str | None = None,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Record one non-fatal degradation without ever raising to the caller."""
    ts = _now()
    etype = type(exc).__name__ if exc is not None else "NON_EXCEPTION_DEGRADATION"
    message = str(exc) if exc is not None else ""
    fp = _fingerprint(component, operation, etype, fallback)
    event = {
        "fingerprint": fp,
        "first_seen": ts,
        "last_seen": ts,
        "component": str(component),
        "operation": str(operation),
        "severity": str(severity).upper(),
        "exception_type": etype,
        "message": message[:1000],
        "fallback": str(fallback),
        "decision_authority_suppressed": bool(decision_authority_suppressed),
        "source": source,
        "context": dict(context or {}),
        "occurrence_count": 1,
        "execution_authority": "NONE",
    }
    try:
        with _LOCK:
            _MEMORY.append(dict(event))
        with _connect() as c:
            c.execute("""
                INSERT INTO degradation_events(
                  fingerprint,first_seen,last_seen,component,operation,severity,
                  exception_type,message,fallback,decision_authority_suppressed,
                  source,context_json,occurrence_count
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)
                ON CONFLICT(fingerprint) DO UPDATE SET
                  last_seen=excluded.last_seen,
                  severity=excluded.severity,
                  message=excluded.message,
                  decision_authority_suppressed=excluded.decision_authority_suppressed,
                  source=excluded.source,
                  context_json=excluded.context_json,
                  occurrence_count=degradation_events.occurrence_count+1
            """, (
                fp, ts, ts, event["component"], event["operation"], event["severity"],
                etype, event["message"], event["fallback"], int(bool(decision_authority_suppressed)),
                source, json.dumps(event["context"], default=str),
            ))
        return {"ok": True, "recorded": True, "fingerprint": fp}
    except Exception as recorder_error:
        # Never allow observability to become an application outage.
        print(
            f"[APEX67.1 degradation-recorder-failed] {type(recorder_error).__name__}: "
            f"{recorder_error}; original={component}/{operation}/{etype}",
            flush=True,
        )
        return {"ok": False, "recorded": False, "fingerprint": fp}


def snapshot(limit: int = 100) -> dict[str, Any]:
    limit = max(1, min(int(limit), 500))
    rows: list[dict[str, Any]] = []
    source = "SQLITE"
    try:
        with _connect() as c:
            for r in c.execute("""
                SELECT fingerprint,first_seen,last_seen,component,operation,severity,
                       exception_type,message,fallback,decision_authority_suppressed,
                       source,context_json,occurrence_count
                FROM degradation_events
                ORDER BY last_seen DESC LIMIT ?
            """, (limit,)):
                d = dict(r)
                try:
                    d["context"] = json.loads(d.pop("context_json") or "{}")
                except Exception:
                    d["context"] = {}
                    d.pop("context_json", None)
                d["decision_authority_suppressed"] = bool(d["decision_authority_suppressed"])
                rows.append(d)
    except Exception:
        source = "MEMORY_FALLBACK"
        with _LOCK:
            rows = list(reversed(list(_MEMORY)))[:limit]

    total_occurrences = sum(int(r.get("occurrence_count") or 1) for r in rows)
    suppressed = sum(
        int(r.get("occurrence_count") or 1)
        for r in rows if r.get("decision_authority_suppressed")
    )
    by_component: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for r in rows:
        n = int(r.get("occurrence_count") or 1)
        by_component[r.get("component") or "UNKNOWN"] = by_component.get(r.get("component") or "UNKNOWN", 0) + n
        by_severity[r.get("severity") or "UNKNOWN"] = by_severity.get(r.get("severity") or "UNKNOWN", 0) + n

    return {
        "ok": True,
        "status": "DEGRADED" if rows else "HEALTHY",
        "source": source,
        "event_groups": len(rows),
        "occurrences": total_occurrences,
        "decision_authority_suppressed_occurrences": suppressed,
        "by_component": by_component,
        "by_severity": by_severity,
        "events": rows,
        "engine_version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "execution_authority": "NONE",
    }
