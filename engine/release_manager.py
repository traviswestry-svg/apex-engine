"""engine/release_manager.py — APEX 11.0A: release identity + data integrity.

WHY THIS IS PHASE 11.0A
-----------------------
"No new intelligence until data integrity is trusted." Every statistic in 11.1 —
win rate, expectancy, Kelly, calibration — is a computation over stored history.
If the store is silently empty, or the deployed code is not the code you think it
is, those modules do not fail loudly. They report confident numbers derived from
nothing.

So this module answers three questions and refuses to guess at any of them:

    What is actually deployed?        -> release_metadata()
    Is the schema what code expects?  -> migration_status()
    Is the pipeline actually writing? -> data_integrity()

READ-ONLY, ALWAYS
-----------------
Nothing here mutates state, applies a migration, or touches a trade decision. It
reports. `guardrails` says so on every payload, because a release endpoint that
can apply a migration is a release endpoint that can break a live session.

THE HONEST BIT ABOUT SCHEMA VERSIONS
------------------------------------
APEX has no migration framework: tables are created with CREATE TABLE IF NOT
EXISTS and evolved with ad-hoc ALTER. There is no schema_version table, and
PRAGMA user_version is never stamped. So APEX_DATABASE_SCHEMA_VERSION is an
OPERATOR CLAIM, not a measurement — and this module reports it as such rather
than presenting a declared number as a verified one. `verified` is false unless
the value was actually read from the database.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

APPLICATION_VERSION = "16.0.0_INSTITUTIONAL_TRADING_BRAIN"
SEMANTIC_VERSION = "16.0.0"
DATABASE_VERSION = "5"

# Backward-compatible alias used by app.py.
APP_VERSION = APPLICATION_VERSION

FEATURES = [
    "Institutional State",
    "Evidence Graph",
    "Decision Trace",
    "Market Story",
    "Dashboard Evidence",
    "Similarity Engine",
    "Learning Engine",
    "Production Readiness",
    "Market Status",
    "Mission Control 2.0",
    "Institutional Trading Workspace",
    "Institutional Volume Profile Intelligence",
    "Release Manager",
    "Configuration Governance",
    "Dependency Governance",
    "Institutional Intelligence Engine",
    "Institutional Market Structure Engine",
    "Institutional Dealer Positioning Engine",
    "Institutional Options Flow Intelligence",
    "Institutional Probability Engine",
    "Adaptive Learning Engine v2",
    "Institutional Decision Engine",
    "Institutional Volume Profile Intelligence",
    "Institutional Trading Workspace",
    "Institutional Mission Control 2.0",
    "Market Memory Engine",
    "Pre-23 Hardening & Consolidation",
    "Route Assurance",
    "Persistence Governance",
    "Institutional Snapshot",
    "Institutional Trading Brain",
    "Dynamic Evidence Weighting",
    "Conflict Resolution",
    "Thesis Timeline",
    "Confidence Calibration Hooks",
]

# Stores whose emptiness would silently invalidate an 11.1 module. Each names its
# own consequence, so a zero reports what it breaks instead of just being a zero.
_INTEGRITY_TABLES: Dict[str, str] = {
    "premium_recommendations": "Recommendation calibration (11.1) — needs graded history",
    "apex_signals": "Strategy intelligence (11.1) — win rate, expectancy",
    "flow_features": "Similarity engine (11.1) — pre-decision vectors",
    "flow_labels": "Similarity + calibration (11.1) — outcomes",
    "flow_pl_tracking": "Theoretical flow P/L — per-event excursions",
    "flow_pl_cluster_tracking": "Cluster labels — the Step 5 label surface",
    "replay_snapshots": "Historical replay (11.1) — point-in-time bus capture",
}


def _first_env(*names: str) -> Optional[str]:
    for n in names:
        v = os.getenv(n)
        if v:
            return v.strip()
    return None


def _db_path() -> str:
    """Resolved at call time — an import-time bind makes the answer depend on
    which importer won the race (range_intelligence had exactly that bug)."""
    return os.getenv("DB_PATH", "apex_tracking.db")


def release_metadata() -> Dict[str, Any]:
    """What is actually deployed, from the environment rather than from hope.

    APEX_* wins over platform-specific vars: an explicit operator value should
    never be shadowed by whatever the host happened to inject.
    """
    commit = _first_env("APEX_GIT_COMMIT", "RENDER_GIT_COMMIT", "GIT_COMMIT",
                        "SOURCE_VERSION") or "unknown"
    build = _first_env("APEX_BUILD_ID", "RENDER_DEPLOY_ID", "BUILD_ID") or \
        datetime.now(timezone.utc).strftime("%Y.%m.%d.%H%M")
    environment = _first_env("APEX_ENVIRONMENT", "RENDER_SERVICE_NAME", "FLASK_ENV",
                             "ENVIRONMENT") or "unknown"
    deployed_at = _first_env("APEX_DEPLOYED_AT", "RENDER_DEPLOY_CREATED_AT")

    mig = migration_status()
    return {
        "version": SEMANTIC_VERSION,
        "application_version": APPLICATION_VERSION,
        "build": build,
        "commit": commit,
        "commit_known": commit != "unknown",
        "environment": environment,
        "deployed_at": deployed_at,
        "features": list(FEATURES),
        "database_version": DATABASE_VERSION,
        "pending_migrations": mig["pending_migrations"],
        "migration_status": "CURRENT" if mig["ready"] else "PENDING",
        "migrations_verified": mig["verified"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "guardrails": {
            "read_only": True,
            "changes_trade_decisions": False,
            "applies_migrations": False,
            "note": ("This surface reports state. It never mutates the database, "
                     "applies a migration, or influences a trade decision."),
        },
    }


def get_release_metadata() -> Dict[str, Any]:
    """Backward-compatible alias — app.py and release_routes imported this first."""
    return release_metadata()


def _measured_schema_version() -> Optional[str]:
    """PRAGMA user_version from the live DB, or None if never stamped.

    APEX does not currently stamp it, so this is expected to be None — which is
    exactly why a declared version cannot be called verified.
    """
    try:
        with sqlite3.connect(_db_path(), timeout=5) as c:
            v = c.execute("PRAGMA user_version").fetchone()
        if v and int(v[0]) > 0:
            return str(int(v[0]))
        return None
    except Exception:
        return None


def migration_status() -> Dict[str, Any]:
    """Is the database schema what this code expects?

    `ready` is true only when the schema version is KNOWN to match. An undeclared,
    unmeasurable schema reports not-ready with `verified: false` — not a pass.
    "We didn't check" and "we checked and it's fine" are different claims, and
    every 11.1 statistic depends on the difference.
    """
    expected = DATABASE_VERSION
    measured = _measured_schema_version()
    declared = _first_env("APEX_DATABASE_SCHEMA_VERSION")

    if measured is not None:
        actual, source, verified = measured, "database (PRAGMA user_version)", True
    elif declared is not None:
        actual, source, verified = (declared,
                                    "operator claim (APEX_DATABASE_SCHEMA_VERSION)", False)
    else:
        actual, source, verified = None, "not declared and not stamped in the database", False

    pending: List[Dict[str, Any]] = []
    if actual is None:
        ready = False
        note = ("Schema version is neither stamped in the database (PRAGMA user_version) "
                "nor declared via APEX_DATABASE_SCHEMA_VERSION, so it cannot be checked. "
                "Reporting not-ready rather than assuming a pass.")
    elif str(actual) == str(expected):
        ready = True
        note = (f"Schema {actual} matches the version this code expects."
                + ("" if verified else
                   " Source is an operator claim, not a measurement."))
    else:
        ready = False
        pending.append({
            "from_version": str(actual),
            "to_version": str(expected),
            "detail": (f"Database reports schema {actual}; this build expects {expected}. "
                       f"APEX has no migration framework — tables are created with "
                       f"CREATE TABLE IF NOT EXISTS and evolved with ad-hoc ALTER — so "
                       f"there is no migration to run automatically. This is a signal to "
                       f"check the deploy, not an action to take here."),
        })
        note = f"Schema mismatch: database at {actual}, code expects {expected}."

    return {
        "ready": ready,
        "verified": verified,
        "expected_version": str(expected),
        "actual_version": str(actual) if actual is not None else None,
        "source": source,
        "pending_migrations": pending,
        "note": note,
        "guardrails": {"read_only": True, "applies_migrations": False},
    }


def data_integrity() -> Dict[str, Any]:
    """Is the pipeline actually writing what 11.1 will compute over?

    This is the point of Phase 11.0A. A statistic over an empty table does not
    crash — it reports a confident number derived from nothing. This names every
    store that matters, its row count, and what breaks if it stays at zero.
    """
    tables: Dict[str, Any] = {}
    ok = True
    try:
        with sqlite3.connect(_db_path(), timeout=5) as c:
            present = {r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            for t, why in _INTEGRITY_TABLES.items():
                if t not in present:
                    tables[t] = {"rows": None, "state": "MISSING", "depends_on_it": why}
                    ok = False
                    continue
                try:
                    n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                except Exception as e:
                    tables[t] = {"rows": None, "state": f"UNREADABLE ({e})",
                                 "depends_on_it": why}
                    ok = False
                    continue
                tables[t] = {"rows": n, "state": "ACCUMULATING" if n else "EMPTY",
                             "depends_on_it": why}
    except Exception as e:
        return {"ok": False, "note": f"data integrity check recovered: {e}",
                "tables": {}, "db_path": _db_path(),
                "statistics_supportable": False}

    empty = sorted(k for k, v in tables.items() if v.get("state") == "EMPTY")
    missing = sorted(k for k, v in tables.items() if v.get("state") == "MISSING")
    return {
        "ok": ok,
        "db_path": _db_path(),
        "tables": tables,
        "empty_tables": empty,
        "missing_tables": missing,
        "statistics_supportable": not empty and not missing,
        "note": ("Every 11.1 statistic is a computation over these tables. An empty "
                 "table does not make a module fail — it makes it confident about "
                 "nothing. Counts here are GLOBAL; matched-neighbourhood counts are "
                 "far smaller (see /api/feature_store/coverage)."),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
