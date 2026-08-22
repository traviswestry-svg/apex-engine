"""APEX 68.5.0 — Calibration Activation & Truth Closure.

Human-approved, bounded activation boundary for dynamic-state calibration
candidates.  Activation is never automatic and cannot create direction, change
suppression/watch-only state, mutate execution authority, or modify broker/risk
configuration.  It may only apply small additive adjustments to the existing
68.2 dynamic-state policy outputs when the activated candidate's calibrated
bucket is present.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

VERSION = "68.5.3"
SCHEMA_VERSION = "apex.calibration_activation.v1"

# Hard production envelopes. Requests outside these limits are rejected rather
# than silently clipped so the human reviewer sees exactly what will run.
ACTIVATION_ROLES = {"SYSTEM_ARCHITECTURE", "TRADING_LOGIC", "RISK_CONTROLS"}

BOUNDS = {
    "threshold_adjustment_points": (-3.0, 3.0),
    "conviction_penalty_points": (-3.0, 3.0),
    "consensus_penalty_points": (-2.0, 2.0),
}

READ_TIMEOUT_SECONDS = 0.35
READ_BUSY_TIMEOUT_MS = 250


def _readonly_connect(path: str | Path):
    """Open a bounded, non-mutating connection for runtime/readout paths.

    Reads must never wait behind scanner writers long enough to stall a web or
    decision thread.  No healing, WAL mutation, or schema creation occurs here.
    """
    from .canonical_persistence import connection as canonical_connection
    return canonical_connection(
        path, read_only=True, timeout=READ_TIMEOUT_SECONDS, wal=False, heal=False,
        busy_timeout_ms=READ_BUSY_TIMEOUT_MS,
    )




def _read_availability(path: str | Path, exc: Exception | None = None) -> Dict[str, Any]:
    """Classify bounded read availability without mutating persistence.

    Missing stores are a truthful pre-initialization state, not a product error.
    Busy/locked stores and genuine read failures remain degraded and observable.
    """
    import sqlite3
    resolved = Path(path).expanduser()
    if str(path) not in {":memory:", ""} and not resolved.exists():
        return {
            "status": "MISSING_DB", "read_available": False, "initialized": False,
            "degraded": False, "reason": "STORE_NOT_CREATED_YET",
        }
    if exc is None:
        return {"status": "READY", "read_available": True, "initialized": True, "degraded": False}
    msg = str(exc).lower()
    if isinstance(exc, sqlite3.OperationalError) and ("locked" in msg or "busy" in msg):
        return {
            "status": "BUSY", "read_available": False, "initialized": True,
            "degraded": True, "reason": "SQLITE_BUSY", "error": type(exc).__name__,
        }
    if isinstance(exc, sqlite3.OperationalError) and "unable to open database file" in msg and not resolved.exists():
        return {
            "status": "MISSING_DB", "read_available": False, "initialized": False,
            "degraded": False, "reason": "STORE_NOT_CREATED_YET",
        }
    return {
        "status": "READ_ERROR", "read_available": False, "initialized": resolved.exists(),
        "degraded": True, "reason": "SQLITE_READ_FAILED", "error": type(exc).__name__,
    }


def _empty_read_state(path: str | Path) -> Dict[str, Any] | None:
    state = _read_availability(path)
    return state if state["status"] == "MISSING_DB" else None

def _table_exists(conn, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(v: Any) -> Dict[str, Any]:
    try:
        x = json.loads(v or "{}") if not isinstance(v, Mapping) else dict(v)
        return x if isinstance(x, dict) else {}
    except Exception:
        return {}


def _f(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def ensure_schema(conn) -> None:
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS calibration_activations(
        activation_id TEXT PRIMARY KEY,
        candidate_id TEXT NOT NULL,
        dimension TEXT NOT NULL,
        bucket TEXT NOT NULL,
        activated_at TEXT NOT NULL,
        activated_by TEXT NOT NULL,
        reason TEXT NOT NULL,
        adjustment_json TEXT NOT NULL,
        candidate_integrity_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        rolled_back_at TEXT,
        rolled_back_by TEXT,
        rollback_reason TEXT,
        metadata_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_calibration_activation_status
      ON calibration_activations(status,dimension,bucket,activated_at);
    CREATE INDEX IF NOT EXISTS idx_calibration_activation_candidate
      ON calibration_activations(candidate_id,activated_at);
    ''')



def initialize_governance_store(path: str | Path) -> Dict[str, Any]:
    """Idempotently initialize calibration governance on a controlled write path.

    This function is intended for application composition/startup or an explicit
    governed writer.  GET/read routes must not call it.  It creates the base
    evidence schema, the 68.4 candidate/review schema, and the 68.5 activation
    schema in one canonical writer transaction boundary.
    """
    from .evidence_pipeline import _connect
    from .dynamic_state_calibration_governance import ensure_schema as ensure_candidate_schema

    resolved = Path(path).expanduser()
    existed_before = resolved.exists() if str(path) not in {":memory:", ""} else True
    with _connect(path) as conn:
        ensure_candidate_schema(conn)
        ensure_schema(conn)
        conn.commit()
        candidate_ready = _table_exists(conn, "dynamic_calibration_candidates")
        review_ready = _table_exists(conn, "dynamic_calibration_reviews")
        activation_ready = _table_exists(conn, "calibration_activations")
    initialized = bool(candidate_ready and review_ready and activation_ready)
    return {
        "ok": initialized,
        "status": "READY" if initialized else "INITIALIZATION_INCOMPLETE",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "initialized": initialized,
        "created_store": (not existed_before and resolved.exists()) if str(path) not in {":memory:", ""} else False,
        "path": str(resolved),
        "persistent_render_path": str(resolved).startswith("/data/"),
        "tables": {
            "dynamic_calibration_candidates": candidate_ready,
            "dynamic_calibration_reviews": review_ready,
            "calibration_activations": activation_ready,
        },
        "automatic_activation": False,
        "execution_authority": False,
    }

def _candidate(conn, candidate_id: str):
    from .dynamic_state_calibration_governance import ensure_schema as ensure_candidate_schema
    ensure_candidate_schema(conn)
    return conn.execute(
        "SELECT * FROM dynamic_calibration_candidates WHERE candidate_id=?", (candidate_id,)
    ).fetchone()


def _candidate_integrity_valid(row) -> bool:
    from .dynamic_state_calibration_governance import _integrity_hash
    immutable = {
        "candidate_id": row["candidate_id"],
        "created_at": row["created_at"],
        "dimension": row["dimension"],
        "challenger_bucket": str(row["challenger_bucket"]),
        "incumbent_bucket": str(row["incumbent_bucket"]),
        "expected_relation": str(row["expected_relation"]).upper(),
        "proposal": _load(row["proposal_json"]),
        "thresholds": _load(row["thresholds_json"]),
    }
    return _integrity_hash(immutable) == row["integrity_hash"]


def _validated_adjustment(proposal: Mapping[str, Any]) -> tuple[Optional[Dict[str, float]], list[str]]:
    out: Dict[str, float] = {}
    blockers: list[str] = []
    for key, value in dict(proposal or {}).items():
        if key not in BOUNDS:
            continue
        number = _f(value)
        if number is None:
            blockers.append(f"NON_NUMERIC_{key.upper()}")
            continue
        lo, hi = BOUNDS[key]
        if number < lo or number > hi:
            blockers.append(f"OUT_OF_BOUNDS_{key.upper()}")
            continue
        out[key] = round(number, 3)
    if not out:
        blockers.append("NO_SUPPORTED_POLICY_ADJUSTMENT")
    return (out if not blockers else None), blockers


def activate_candidate(path: str | Path, candidate_id: str, *, actor: str, reason: str) -> Dict[str, Any]:
    """Activate one already-approved calibration recommendation.

    Human activation is a distinct step after 68.4 review approval.  The
    candidate's immutable integrity hash is re-verified immediately before
    activation and the requested adjustment must fit the hard 68.5 envelope.
    """
    from .evidence_pipeline import _connect
    if not str(actor or "").strip() or not str(reason or "").strip():
        return {"ok": False, "status": "APPROVAL_REQUIRED", "error": "actor and reason are required", "production_effect": "NONE"}
    if str(actor).upper() not in ACTIVATION_ROLES:
        return {"ok": False, "status": "APPROVAL_REQUIRED", "error": "actor must be an authorized calibration activation role",
                "required_roles": sorted(ACTIVATION_ROLES), "production_effect": "NONE"}
    actor = str(actor).upper()
    with _connect(path) as conn:
        ensure_schema(conn)
        row = _candidate(conn, candidate_id)
        if not row:
            return {"ok": False, "status": "UNAVAILABLE", "error": "candidate not found", "production_effect": "NONE"}
        if str(row["status"]) != "APPROVED":
            return {"ok": False, "status": str(row["status"]), "error": "candidate must be human-approved before activation", "production_effect": "NONE"}
        if not _candidate_integrity_valid(row):
            return {"ok": False, "status": "INTEGRITY_BLOCKED", "error": "candidate integrity hash mismatch", "production_effect": "NONE"}
        adjustment, blockers = _validated_adjustment(_load(row["proposal_json"]))
        if blockers:
            return {"ok": False, "status": "POLICY_BOUNDS_BLOCKED", "blockers": blockers, "bounds": BOUNDS, "production_effect": "NONE"}

        dimension = str(row["dimension"])
        bucket = str(row["challenger_bucket"])
        # Only one active calibration may govern a given dimension/bucket.
        conn.execute(
            """UPDATE calibration_activations
               SET status='ROLLED_BACK',rolled_back_at=?,rolled_back_by=?,rollback_reason=?
               WHERE status='ACTIVE' AND dimension=? AND bucket=?""",
            (_now(), actor, "SUPERSEDED_BY_NEW_ACTIVATION", dimension, bucket),
        )
        aid = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO calibration_activations(
               activation_id,candidate_id,dimension,bucket,activated_at,activated_by,reason,
               adjustment_json,candidate_integrity_hash,status,metadata_json
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (aid, candidate_id, dimension, bucket, _now(), actor, reason,
             json.dumps(adjustment, sort_keys=True), row["integrity_hash"], "ACTIVE",
             json.dumps({
                 "automatic_activation": False,
                 "bounded_adjustment": True,
                 "execution_authority": False,
                 "direction_generation": False,
                 "suppression_mutation": False,
                 "watch_only_mutation": False,
             }, sort_keys=True)),
        )
    return {
        "ok": True, "status": "ACTIVE", "activation_id": aid, "candidate_id": candidate_id,
        "dimension": dimension, "bucket": bucket, "adjustment": adjustment,
        "production_effect": "BOUNDED_DYNAMIC_STATE_POLICY_ADJUSTMENT",
        "automatic_activation": False, "rollback_available": True,
        "execution_authority": False,
    }


def rollback_activation(path: str | Path, activation_id: str, *, actor: str, reason: str) -> Dict[str, Any]:
    from .evidence_pipeline import _connect
    if not str(actor or "").strip() or not str(reason or "").strip():
        return {"ok": False, "status": "APPROVAL_REQUIRED", "error": "actor and reason are required"}
    if str(actor).upper() not in ACTIVATION_ROLES:
        return {"ok": False, "status": "APPROVAL_REQUIRED", "error": "actor must be an authorized calibration activation role",
                "required_roles": sorted(ACTIVATION_ROLES)}
    actor = str(actor).upper()
    with _connect(path) as conn:
        ensure_schema(conn)
        row = conn.execute("SELECT * FROM calibration_activations WHERE activation_id=?", (activation_id,)).fetchone()
        if not row:
            return {"ok": False, "status": "UNAVAILABLE", "error": "activation not found"}
        if row["status"] != "ACTIVE":
            return {"ok": False, "status": row["status"], "error": "activation is not active"}
        conn.execute(
            """UPDATE calibration_activations
               SET status='ROLLED_BACK',rolled_back_at=?,rolled_back_by=?,rollback_reason=?
               WHERE activation_id=?""",
            (_now(), actor, reason, activation_id),
        )
    return {"ok": True, "status": "ROLLED_BACK", "activation_id": activation_id,
            "production_effect": "REMOVED", "execution_authority": False}


def _dimension_values(dynamic_state: Mapping[str, Any], *, policy_state: str, alert_state: str) -> Dict[str, str]:
    ds = dict(dynamic_state or {})
    event = dict(ds.get("event_phase") or {})
    term = dict(ds.get("gamma_term_structure") or {})
    residual = dict(ds.get("residual_pressure") or {})
    flow = dict(ds.get("flow_excitation") or {})
    ief = _f(flow.get("independent_evidence_factor"))
    if ief is None:
        flow_bucket = str(flow.get("independence_bucket") or "UNKNOWN").upper()
    elif ief < 0.25:
        flow_bucket = "HIGHLY_REDUNDANT"
    elif ief < 0.50:
        flow_bucket = "PARTLY_REDUNDANT"
    elif ief < 0.75:
        flow_bucket = "MOSTLY_INDEPENDENT"
    else:
        flow_bucket = "INDEPENDENT"
    return {
        "event_phase": str(event.get("phase") or "NORMAL").upper(),
        "gamma_term_divergence": "1" if bool(term.get("term_divergence")) else "0",
        "near_term_gamma_fragility": "1" if bool(term.get("near_term_fragility")) else "0",
        "residual_pressure_opposes": "1" if bool(residual.get("opposes_direction")) else "0",
        "flow_independence_bucket": flow_bucket,
        "alert_state": str(alert_state or "UNKNOWN").upper(),
        "policy_state": str(policy_state or "UNKNOWN").upper(),
    }


def resolve_active_adjustments(path: str | Path, dynamic_state: Mapping[str, Any], *, policy_state: str, alert_state: str) -> Dict[str, Any]:
    """Resolve active adjustments with a bounded, read-only DB lookup.

    If persistence is busy/unavailable, production safely runs the existing
    heuristic policy for this evaluation rather than blocking the request or
    decision thread.
    """
    values = _dimension_values(dynamic_state, policy_state=policy_state, alert_state=alert_state)
    totals = {key: 0.0 for key in BOUNDS}
    applied = []
    missing = _empty_read_state(path)
    if missing:
        return {"active": False, "adjustment": totals, "applied": [], "context": values,
                **missing, "execution_authority": False}
    try:
        with _readonly_connect(path) as conn:
            if not _table_exists(conn, "calibration_activations"):
                return {"active": False, "adjustment": totals, "applied": [], "context": values,
                        "status": "NO_ACTIVATION_TABLE", "degraded": False}
            rows = conn.execute(
                "SELECT * FROM calibration_activations WHERE status='ACTIVE' ORDER BY activated_at"
            ).fetchall()
            for row in rows:
                if values.get(str(row["dimension"])) != str(row["bucket"]).upper():
                    continue
                adjustment = _load(row["adjustment_json"])
                for key in totals:
                    value = _f(adjustment.get(key))
                    if value is not None:
                        totals[key] += value
                applied.append({
                    "activation_id": row["activation_id"], "candidate_id": row["candidate_id"],
                    "dimension": row["dimension"], "bucket": row["bucket"], "adjustment": adjustment,
                })
    except Exception as exc:
        return {"active": False, "adjustment": totals, "applied": [], "context": values,
                **_read_availability(path, exc), "execution_authority": False}

    aggregate_caps = {
        "threshold_adjustment_points": (-5.0, 5.0),
        "conviction_penalty_points": (-5.0, 5.0),
        "consensus_penalty_points": (-3.0, 3.0),
    }
    for key, (lo, hi) in aggregate_caps.items():
        totals[key] = round(max(lo, min(hi, totals[key])), 3)
    return {"active": bool(applied), "adjustment": totals, "applied": applied,
            "context": values, "aggregate_caps": aggregate_caps, "status": "READY",
            "degraded": False}


def eligibility_readout(path: str | Path) -> Dict[str, Any]:
    """Fast, read-only eligibility summary; never performs calibration aggregation."""
    from .dynamic_state_outcome_calibration import MIN_SAMPLE
    counts = {}
    decision_contexts = 0
    graded_contexts = 0
    active = 0
    missing = _empty_read_state(path)
    if missing:
        return {"ok": True, **missing, "eligibility_mode": "HEURISTIC", "graded_contexts": 0,
                "decision_contexts": 0, "minimum_sample_per_bucket": MIN_SAMPLE,
                "candidate_counts": {}, "active_calibrations": 0,
                "automatic_activation": False, "human_activation_required": True,
                "production_effect": "NONE", "execution_authority": False}
    try:
        with _readonly_connect(path) as conn:
            if _table_exists(conn, "dynamic_state_decision_context"):
                decision_contexts = int(conn.execute(
                    "SELECT COUNT(*) n FROM dynamic_state_decision_context"
                ).fetchone()["n"] or 0)
            if _table_exists(conn, "dynamic_state_decision_context") and _table_exists(conn, "grading_results"):
                graded_contexts = int(conn.execute(
                    "SELECT COUNT(*) n FROM dynamic_state_decision_context c "
                    "JOIN grading_results g ON g.decision_id=c.decision_id WHERE g.status='GRADED'"
                ).fetchone()["n"] or 0)
            if _table_exists(conn, "dynamic_calibration_candidates"):
                counts = {str(r["status"]): int(r["n"] or 0) for r in conn.execute(
                    "SELECT status,COUNT(*) n FROM dynamic_calibration_candidates GROUP BY status"
                ).fetchall()}
            if _table_exists(conn, "calibration_activations"):
                active = int(conn.execute(
                    "SELECT COUNT(*) n FROM calibration_activations WHERE status='ACTIVE'"
                ).fetchone()["n"] or 0)
    except Exception as exc:
        availability = _read_availability(path, exc)
        return {"ok": False, **availability, "eligibility_mode": "HEURISTIC", "graded_contexts": 0,
                "decision_contexts": 0, "minimum_sample_per_bucket": MIN_SAMPLE,
                "candidate_counts": {}, "active_calibrations": 0,
                "automatic_activation": False, "human_activation_required": True,
                "production_effect": "NONE", "execution_authority": False}

    if active > 0:
        mode = "ACTIVE"
    elif int(counts.get("APPROVED") or 0) > 0:
        mode = "APPROVED"
    elif int(counts.get("ELIGIBLE_FOR_REVIEW") or 0) > 0:
        mode = "ELIGIBLE"
    elif graded_contexts > 0:
        mode = "LEARNING"
    else:
        mode = "HEURISTIC"
    return {
        "ok": True, "status": mode, "eligibility_mode": mode, "read_available": True, "initialized": True, "graded_contexts": graded_contexts,
        "decision_contexts": decision_contexts, "minimum_sample_per_bucket": MIN_SAMPLE,
        "candidate_counts": counts, "active_calibrations": active,
        "automatic_activation": False, "human_activation_required": True,
        "production_effect": "BOUNDED" if active else "NONE", "degraded": False,
    }


def activation_status(path: str | Path, limit: int = 100) -> Dict[str, Any]:
    activations = []
    missing = _empty_read_state(path)
    if missing:
        return {"ok": True, **missing, "version": VERSION, "schema_version": SCHEMA_VERSION,
                "active_count": 0, "activations": [], "production_effect": "NONE",
                "execution_authority": False,
                "policy": {"automatic_activation": False, "human_activation_required": True,
                           "bounded_adjustments": BOUNDS, "execution_authority": False,
                           "suppression_and_watch_only_immutable": True}}
    try:
        with _readonly_connect(path) as conn:
            if _table_exists(conn, "calibration_activations"):
                rows = conn.execute(
                    "SELECT * FROM calibration_activations ORDER BY activated_at DESC LIMIT ?",
                    (max(1, min(int(limit), 500)),),
                ).fetchall()
                for row in rows:
                    activations.append({
                        "activation_id": row["activation_id"], "candidate_id": row["candidate_id"],
                        "dimension": row["dimension"], "bucket": row["bucket"], "activated_at": row["activated_at"],
                        "activated_by": row["activated_by"], "reason": row["reason"], "adjustment": _load(row["adjustment_json"]),
                        "status": row["status"], "rolled_back_at": row["rolled_back_at"],
                        "rolled_back_by": row["rolled_back_by"], "rollback_reason": row["rollback_reason"],
                    })
    except Exception as exc:
        return {"ok": False, **_read_availability(path, exc), "version": VERSION,
                "schema_version": SCHEMA_VERSION, "active_count": 0, "activations": [],
                "production_effect": "NONE", "execution_authority": False}
    return {
        "ok": True, "status": "READY", "version": VERSION, "schema_version": SCHEMA_VERSION,
        "lifecycle": ["HEURISTIC", "LEARNING", "ELIGIBLE", "APPROVED", "ACTIVE", "ROLLED_BACK"],
        "active_count": sum(1 for x in activations if x["status"] == "ACTIVE"),
        "activations": activations, "degraded": False,
        "policy": {"automatic_activation": False, "human_activation_required": True,
                   "bounded_adjustments": BOUNDS, "execution_authority": False,
                   "suppression_and_watch_only_immutable": True},
    }

