"""APEX 65.8 — Evidence Accumulation Observatory.

Read-only cross-subsystem diagnostics.  This module does not create evidence,
change thresholds, grade outcomes, backfill history, or influence decisions.
It answers one operational question: are APEX's existing learning stores
actually accumulating real evidence, and where is each lifecycle blocked?
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

VERSION = "65.8.0_EVIDENCE_ACCUMULATION_OBSERVATORY"
SCHEMA_VERSION = "apex.evidence_accumulation.v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first_existing(*paths: Optional[str]) -> Optional[str]:
    clean = [str(p) for p in paths if p]
    for p in clean:
        if Path(p).exists():
            return p
    return clean[0] if clean else None


def _resolved_paths() -> Dict[str, Optional[str]]:
    """Resolve the same durable stores used by existing engines without creating them."""
    try:
        from . import historical_level_calibration as hlce
        calibration = hlce._db_path()  # authoritative existing resolver
    except Exception:
        calibration = os.getenv("APEX_CALIBRATION_DB", "apex_calibration.db")

    try:
        from . import market_memory_engine_v220 as mm
        market_memory = mm._db_path()  # authoritative existing resolver
    except Exception:
        market_memory = os.getenv("APEX_MARKET_MEMORY_DB", "apex_market_memory.db")

    def durable(env_name: str, filename: str) -> str:
        configured = os.getenv(env_name, "").strip()
        if configured:
            return configured
        data_path = f"/data/{filename}"
        # Prefer the durable copy when it exists. Do not create it here.
        return _first_existing(data_path, filename) or filename

    return {
        "calibration": calibration,
        "market_memory": market_memory,
        "governance": durable("APEX_GOVERNANCE_DB", "apex_governance.db"),
        "similarity": durable("APEX_SIMILARITY_DB", "apex_similarity.db"),
        "research": durable("APEX_RESEARCH_DB", "apex_research.db"),
        "evidence": durable("APEX_EVIDENCE_DB", "apex_evidence.db"),
    }


def _query(path: Optional[str], queries: Mapping[str, str]) -> Dict[str, Any]:
    if not path:
        return {"available": False, "state": "UNCONFIGURED", "path": None, "counts": {}, "error": "path_not_configured"}
    p = Path(path)
    if not p.exists():
        return {"available": False, "state": "NOT_CREATED", "path": str(p), "counts": {}, "error": None}
    try:
        uri = f"file:{p.resolve()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=2.0) as conn:
            conn.row_factory = sqlite3.Row
            counts: Dict[str, Any] = {}
            for key, sql in queries.items():
                try:
                    row = conn.execute(sql).fetchone()
                    counts[key] = row[0] if row else None
                except sqlite3.DatabaseError:
                    counts[key] = None
        return {"available": True, "state": "READABLE", "path": str(p), "counts": counts, "error": None,
                "storage_bytes": p.stat().st_size}
    except Exception as exc:
        return {"available": False, "state": "ERROR", "path": str(p), "counts": {},
                "error": f"{type(exc).__name__}: {exc}"}


def _calibration(path: Optional[str]) -> Dict[str, Any]:
    out = _query(path, {
        "daily_levels": "SELECT COUNT(*) FROM daily_levels",
        "price_samples": "SELECT COUNT(*) FROM level_price_samples",
        "interactions": "SELECT COUNT(*) FROM level_interactions",
        "ungraded_interactions": "SELECT COUNT(*) FROM level_interactions WHERE graded=0",
        "graded_interactions": "SELECT COUNT(*) FROM level_interactions WHERE graded=1",
        "outcomes": "SELECT COUNT(*) FROM level_outcomes",
        "statistics": "SELECT COUNT(*) FROM calibration_statistics",
        "last_level_at": "SELECT MAX(registered_at) FROM daily_levels",
        "last_price_sample_at": "SELECT MAX(ts) FROM level_price_samples",
        "last_interaction_at": "SELECT MAX(ts) FROM level_interactions",
        "last_outcome_at": "SELECT MAX(graded_at) FROM level_outcomes",
    })
    c = out.get("counts") or {}
    lifecycle = [
        {"stage": "LEVEL_REGISTRATION", "ready": int(c.get("daily_levels") or 0) > 0, "count": int(c.get("daily_levels") or 0)},
        {"stage": "PRICE_SAMPLING", "ready": int(c.get("price_samples") or 0) > 0, "count": int(c.get("price_samples") or 0)},
        {"stage": "INTERACTION_DETECTION", "ready": int(c.get("interactions") or 0) > 0, "count": int(c.get("interactions") or 0)},
        {"stage": "OUTCOME_GRADING", "ready": int(c.get("outcomes") or 0) > 0, "count": int(c.get("outcomes") or 0)},
        {"stage": "STATISTICS", "ready": int(c.get("statistics") or 0) > 0, "count": int(c.get("statistics") or 0)},
    ]
    first_blocked = next((x["stage"] for x in lifecycle if not x["ready"]), None)
    out.update({"lifecycle": lifecycle, "first_blocked_stage": first_blocked,
                "state": "ACCUMULATING" if lifecycle[1]["ready"] else ("REGISTERED" if lifecycle[0]["ready"] else out.get("state"))})
    return out


def _store(path: Optional[str], kind: str) -> Dict[str, Any]:
    specs = {
        "market_memory": {
            "sessions": "SELECT COUNT(*) FROM market_memory_sessions",
            "graded_sessions": "SELECT COUNT(*) FROM market_memory_sessions WHERE outcome_status='GRADED'",
            "last_observation_at": "SELECT MAX(observed_at) FROM market_memory_sessions",
        },
        "governance": {
            "historical_events": "SELECT COUNT(*) FROM historical_events",
            "graded_outcomes": "SELECT COUNT(*) FROM graded_outcomes",
            "feature_vectors": "SELECT COUNT(*) FROM feature_vectors",
            "model_registry": "SELECT COUNT(*) FROM model_registry",
            "shadow_results": "SELECT COUNT(*) FROM shadow_results",
            "last_graded_at": "SELECT MAX(graded_at) FROM graded_outcomes",
        },
        "similarity": {
            "feature_vectors": "SELECT COUNT(*) FROM institutional_feature_vectors",
            "queries": "SELECT COUNT(*) FROM similarity_queries",
            "last_observation_at": "SELECT MAX(observed_at) FROM institutional_feature_vectors",
        },
        "research": {
            "runs": "SELECT COUNT(*) FROM research_runs",
            "findings": "SELECT COUNT(*) FROM research_findings",
            "last_run_at": "SELECT MAX(created_at) FROM research_runs",
        },
        "evidence": {
            "packages": "SELECT COUNT(*) FROM evidence_packages",
            "snapshots": "SELECT COUNT(*) FROM evidence_snapshots",
            "timeline": "SELECT COUNT(*) FROM evidence_timeline",
            "integrity_results": "SELECT COUNT(*) FROM evidence_integrity_results",
            "last_package_at": "SELECT MAX(created_at) FROM evidence_packages",
        },
    }
    out = _query(path, specs[kind])
    numeric = [v for v in (out.get("counts") or {}).values() if isinstance(v, int)]
    total = sum(numeric)
    if out.get("available"):
        out["state"] = "ACCUMULATING" if total > 0 else "COLD"
    out["has_evidence"] = total > 0
    return out


def build_observatory() -> Dict[str, Any]:
    paths = _resolved_paths()
    stores = {
        "calibration": _calibration(paths["calibration"]),
        "market_memory": _store(paths["market_memory"], "market_memory"),
        "governance": _store(paths["governance"], "governance"),
        "similarity": _store(paths["similarity"], "similarity"),
        "research": _store(paths["research"], "research"),
        "evidence": _store(paths["evidence"], "evidence"),
    }
    cold = [name for name, item in stores.items() if item.get("state") in {"COLD", "NOT_CREATED", "UNCONFIGURED"}]
    errors = [name for name, item in stores.items() if item.get("state") == "ERROR"]
    accumulating = [name for name, item in stores.items() if item.get("state") in {"ACCUMULATING", "REGISTERED"}]

    # Observatory is diagnostic only. It never unlocks production behavior.
    if errors:
        state = "DEGRADED"
    elif cold:
        state = "PARTIAL_ACCUMULATION" if accumulating else "COLD_START"
    else:
        state = "ACCUMULATING"

    return {
        "ok": not errors,
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "state": state,
        "stores": stores,
        "summary": {
            "store_count": len(stores),
            "accumulating": accumulating,
            "cold": cold,
            "errors": errors,
            "all_stores_have_evidence": not cold and not errors,
        },
        "guardrails": {
            "read_only": True,
            "creates_evidence": False,
            "grades_outcomes": False,
            "changes_learning_thresholds": False,
            "backfills_history": False,
            "decision_influence": "NONE",
            "execution_influence": "NONE",
        },
        "generated_at": _now(),
    }
