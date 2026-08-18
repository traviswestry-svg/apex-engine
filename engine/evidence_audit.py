"""APEX 50.7.2 — Read-only production evidence inventory.

This module never creates, migrates, or mutates a database.  It inspects the
persistent HLCE/LTPE and governance stores so operators can prove how much
historical evidence and forecast archive data actually exists.
"""
from __future__ import annotations

from .canonical_persistence import connect as canonical_connect

import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from .persistent_store import persistent_sqlite_path

VERSION = "50.7.2_EVIDENCE_AUDIT"

CALIBRATION_TABLES = {
    "daily_levels": ("session_date", "registered_at"),
    "level_interactions": ("session_date", "ts"),
    "level_outcomes": ("session_date", "graded_at"),
    "level_transition_observations": ("session_date", "created_at"),
    "level_transition_statistics": (None, "updated_at"),
}

GOVERNANCE_TABLES = {
    "apex49_morning_snapshots": ("session_date", "generated_at"),
    "apex49_morning_revisions": ("session_date", "generated_at"),
    "apex49_evening_recaps": ("session_date", "generated_at"),
    "apex5071_readiness_archive": ("session_date", "captured_at"),
}


def _resolve(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def _ro_connect(path: str) -> sqlite3.Connection:
    # Canonical read-only mode guarantees this diagnostic cannot create/modify data.
    return canonical_connect(path, read_only=True, timeout=3, wal=False, heal=False)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.DatabaseError:
        return set()


def _scalar(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> Any:
    row = conn.execute(sql, tuple(params)).fetchone()
    return row[0] if row else None


def _table_summary(conn: sqlite3.Connection, table: str,
                   session_col: Optional[str], time_col: Optional[str]) -> Dict[str, Any]:
    cols = _columns(conn, table)
    if not cols:
        return {"exists": False, "count": 0}
    out: Dict[str, Any] = {"exists": True, "count": int(_scalar(conn, f"SELECT COUNT(*) FROM {table}") or 0)}
    if session_col and session_col in cols:
        first = _scalar(conn, f"SELECT MIN({session_col}) FROM {table}")
        last = _scalar(conn, f"SELECT MAX({session_col}) FROM {table}")
        distinct = _scalar(conn, f"SELECT COUNT(DISTINCT {session_col}) FROM {table}")
        out.update({"first_session_date": first, "last_session_date": last, "session_count": int(distinct or 0)})
    if time_col and time_col in cols:
        out["oldest_record_at"] = _scalar(conn, f"SELECT MIN({time_col}) FROM {table}")
        out["newest_record_at"] = _scalar(conn, f"SELECT MAX({time_col}) FROM {table}")
    return out


def _inspect_store(path: str, tables: Dict[str, tuple[Optional[str], Optional[str]]]) -> Dict[str, Any]:
    resolved = _resolve(path)
    p = Path(resolved)
    result: Dict[str, Any] = {
        "path": resolved,
        "exists": p.exists(),
        "size_bytes": p.stat().st_size if p.exists() else 0,
        "tables": {},
        "diagnostics": [],
    }
    if not p.exists():
        result["status"] = "MISSING"
        return result
    try:
        with _ro_connect(resolved) as conn:
            existing = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            for table, (session_col, time_col) in tables.items():
                if table not in existing:
                    result["tables"][table] = {"exists": False, "count": 0}
                    continue
                result["tables"][table] = _table_summary(conn, table, session_col, time_col)
        result["status"] = "HEALTHY"
    except (sqlite3.DatabaseError, OSError, ValueError) as exc:
        result["status"] = "DEGRADED"
        result["diagnostics"].append({"error_type": type(exc).__name__, "error": str(exc)})
    return result


def evidence_audit(*, calibration_path: Optional[str] = None,
                   governance_path: Optional[str] = None) -> Dict[str, Any]:
    if not calibration_path:
        from .historical_level_calibration import _db_path
        calibration_path = _db_path()
    if not governance_path:
        governance_path = persistent_sqlite_path("APEX_GOVERNANCE_DB", "apex_governance.db")

    calibration = _inspect_store(calibration_path, CALIBRATION_TABLES)
    governance = _inspect_store(governance_path, GOVERNANCE_TABLES)
    ct = calibration.get("tables") or {}
    gt = governance.get("tables") or {}

    interactions = int((ct.get("level_interactions") or {}).get("count") or 0)
    outcomes = int((ct.get("level_outcomes") or {}).get("count") or 0)
    observations = int((ct.get("level_transition_observations") or {}).get("count") or 0)
    stats = int((ct.get("level_transition_statistics") or {}).get("count") or 0)

    required_cal = all((ct.get(t) or {}).get("exists") for t in CALIBRATION_TABLES)
    required_gov = all((gt.get(t) or {}).get("exists") for t in GOVERNANCE_TABLES)
    diagnostics = []
    if outcomes > interactions:
        diagnostics.append({"code": "OUTCOMES_GT_INTERACTIONS", "detail": "Outcome count exceeds interaction count."})
    if observations > outcomes:
        diagnostics.append({"code": "TRANSITIONS_GT_OUTCOMES", "detail": "Transition observations exceed graded outcomes; inspect provenance/deduplication."})
    if stats and not observations:
        diagnostics.append({"code": "STATISTICS_WITHOUT_OBSERVATIONS", "detail": "Transition statistics exist without transition observations."})

    status = "HEALTHY"
    if calibration.get("status") == "DEGRADED" or governance.get("status") == "DEGRADED":
        status = "DEGRADED"
    elif not required_cal or not required_gov:
        status = "PARTIAL"

    return {
        "ok": status != "DEGRADED",
        "status": status,
        "version": VERSION,
        "read_only": True,
        "evidence_policy": "EVIDENCE_ONLY_NO_FABRICATION",
        "calibration_store": calibration,
        "governance_store": governance,
        "summary": {
            "daily_levels": int((ct.get("daily_levels") or {}).get("count") or 0),
            "level_interactions": interactions,
            "level_outcomes": outcomes,
            "level_transition_observations": observations,
            "level_transition_statistics": stats,
            "official_morning_briefs": int((gt.get("apex49_morning_snapshots") or {}).get("count") or 0),
            "morning_brief_revisions": int((gt.get("apex49_morning_revisions") or {}).get("count") or 0),
            "evening_recaps": int((gt.get("apex49_evening_recaps") or {}).get("count") or 0),
            "morning_readiness_archives": int((gt.get("apex5071_readiness_archive") or {}).get("count") or 0),
        },
        "integrity": {
            "required_calibration_tables_present": required_cal,
            "required_governance_tables_present": required_gov,
            "outcomes_not_greater_than_interactions": outcomes <= interactions,
            "transition_observations_not_greater_than_outcomes": observations <= outcomes,
        },
        "diagnostics": diagnostics + list(calibration.get("diagnostics") or []) + list(governance.get("diagnostics") or []),
        "semantics": {
            "evening_recap_touch_count": "Count of regular-session bars whose high/low range intersects the level tolerance band for that single session; this is not historical sample size.",
            "historical_probability_sample_size": "Stored in level_transition_statistics.sample_count and derived only from level_transition_observations.",
        },
    }
