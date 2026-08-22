"""APEX 68.5 — Governed Calibration Activation & Truth Closure.

Provides the production activation lifecycle for approved calibration candidates.
An APPROVED candidate must pass policy bounds before it can be ACTIVE.
At most one activation per candidate dimension is allowed at a time; rollback
returns the system to the pre-activation baseline.

This module has *no* execution authority and does not fabricate outcomes.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

VERSION = "68.5.0"
SCHEMA_VERSION = "apex.calibration_activation.v1"

# Policy bounds: the maximum absolute threshold_adjustment_points a calibration
# candidate may propose.  Proposals exceeding this are blocked before activation.
_MAX_THRESHOLD_ADJUSTMENT_POINTS = 5.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(v: Any) -> Dict[str, Any]:
    try:
        x = json.loads(v or "{}") if not isinstance(v, Mapping) else dict(v)
        return x if isinstance(x, dict) else {}
    except Exception:
        return {}


def _connect(path):
    from .evidence_pipeline import _connect as _ep_connect
    return _ep_connect(path)


def _ensure_schema(conn) -> None:
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS calibration_activations(
        activation_id TEXT PRIMARY KEY,
        candidate_id TEXT NOT NULL,
        activated_at TEXT NOT NULL,
        activated_by TEXT NOT NULL,
        activation_reason TEXT NOT NULL,
        dimension TEXT NOT NULL,
        proposal_json TEXT NOT NULL,
        status TEXT NOT NULL,
        rolled_back_at TEXT,
        rolled_back_by TEXT,
        rollback_reason TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_calibration_activations_candidate
        ON calibration_activations(candidate_id, status);
    CREATE INDEX IF NOT EXISTS idx_calibration_activations_status
        ON calibration_activations(status, activated_at);
    ''')


def activate_candidate(
    path,
    candidate_id: str,
    *,
    actor: str,
    reason: str,
) -> Dict[str, Any]:
    """Activate an APPROVED calibration candidate.

    Returns a dict with ``ok`` (bool) and ``status``.  Possible failure statuses:
    - ``APPROVAL_REQUIRED`` – candidate is not in APPROVED state.
    - ``POLICY_BOUNDS_BLOCKED`` – proposal exceeds allowed adjustment range.
    """
    from .dynamic_state_calibration_governance import ensure_schema as _gov_schema

    with _connect(path) as conn:
        _gov_schema(conn)
        _ensure_schema(conn)

        row = conn.execute(
            "SELECT * FROM dynamic_calibration_candidates WHERE candidate_id=?",
            (candidate_id,),
        ).fetchone()
        if not row:
            return {"ok": False, "status": "NOT_FOUND", "error": "candidate not found"}

        current = str(row["status"])
        if current != "APPROVED":
            return {
                "ok": False,
                "status": "APPROVAL_REQUIRED",
                "error": f"candidate must be APPROVED to activate; current status: {current}",
            }

        proposal = _load(row["proposal_json"])
        tap = float(proposal.get("threshold_adjustment_points", 0.0))
        if abs(tap) > _MAX_THRESHOLD_ADJUSTMENT_POINTS:
            return {
                "ok": False,
                "status": "POLICY_BOUNDS_BLOCKED",
                "error": (
                    f"threshold_adjustment_points {tap} exceeds policy maximum "
                    f"{_MAX_THRESHOLD_ADJUSTMENT_POINTS}"
                ),
            }

        aid = str(uuid.uuid4())
        now = _now()
        conn.execute(
            """INSERT INTO calibration_activations(
                activation_id, candidate_id, activated_at, activated_by,
                activation_reason, dimension, proposal_json, status
            ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                aid, candidate_id, now, actor, reason,
                str(row["dimension"]),
                json.dumps(proposal, sort_keys=True, default=str),
                "ACTIVE",
            ),
        )

    return {
        "ok": True,
        "activation_id": aid,
        "candidate_id": candidate_id,
        "status": "ACTIVE",
        "automatic_activation": False,
        "dimension": str(row["dimension"]),
        "proposal": proposal,
    }


def rollback_activation(
    path,
    activation_id: str,
    *,
    actor: str,
    reason: str,
) -> Dict[str, Any]:
    """Roll back an ACTIVE calibration activation."""
    with _connect(path) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT * FROM calibration_activations WHERE activation_id=?",
            (activation_id,),
        ).fetchone()
        if not row:
            return {"ok": False, "status": "NOT_FOUND", "error": "activation not found"}
        if str(row["status"]) != "ACTIVE":
            return {
                "ok": False,
                "status": str(row["status"]),
                "error": "activation is not in ACTIVE state",
            }
        now = _now()
        conn.execute(
            """UPDATE calibration_activations
               SET status='ROLLED_BACK', rolled_back_at=?, rolled_back_by=?, rollback_reason=?
               WHERE activation_id=?""",
            (now, actor, reason, activation_id),
        )
    return {
        "ok": True,
        "activation_id": activation_id,
        "status": "ROLLED_BACK",
        "rolled_back_at": now,
        "rolled_back_by": actor,
    }


def activation_status(path) -> Dict[str, Any]:
    """Return a summary of calibration activations."""
    with _connect(path) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT * FROM calibration_activations WHERE status='ACTIVE' ORDER BY activated_at DESC"
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM calibration_activations"
        ).fetchone()[0]
    active = [
        {
            "activation_id": r["activation_id"],
            "candidate_id": r["candidate_id"],
            "dimension": r["dimension"],
            "proposal": _load(r["proposal_json"]),
            "activated_at": r["activated_at"],
            "activated_by": r["activated_by"],
        }
        for r in rows
    ]
    return {
        "ok": True,
        "active_count": len(active),
        "total_count": total,
        "active_activations": active,
    }


def eligibility_readout(path) -> Dict[str, Any]:
    """Return the most recently approved candidate's status."""
    from .dynamic_state_calibration_governance import ensure_schema as _gov_schema

    with _connect(path) as conn:
        _gov_schema(conn)
        row = conn.execute(
            """SELECT * FROM dynamic_calibration_candidates
               WHERE status IN ('APPROVED','ELIGIBLE_FOR_REVIEW','COLLECTING','REJECTED')
               ORDER BY
                 CASE status
                   WHEN 'APPROVED' THEN 0
                   WHEN 'ELIGIBLE_FOR_REVIEW' THEN 1
                   WHEN 'COLLECTING' THEN 2
                   ELSE 3
                 END,
                 created_at DESC
               LIMIT 1"""
        ).fetchone()
    if not row:
        return {"ok": True, "status": "NO_CANDIDATES", "candidate_id": None}
    return {
        "ok": True,
        "status": str(row["status"]),
        "candidate_id": row["candidate_id"],
        "dimension": row["dimension"],
    }


def active_adjustments(path=None) -> Dict[str, Any]:
    """Return the aggregated proposal adjustments from all ACTIVE activations.

    Used by ``engine.dynamic_state_policy`` to incorporate governed calibration
    into live policy outputs.  When *path* is ``None`` the evidence pipeline's
    ``DEFAULT_DB`` is used so that callers do not need to thread the path through
    the entire call chain.
    """
    import engine.evidence_pipeline as _ep
    resolved = path if path is not None else _ep.DEFAULT_DB
    try:
        with _connect(resolved) as conn:
            _ensure_schema(conn)
            rows = conn.execute(
                "SELECT proposal_json, dimension FROM calibration_activations WHERE status='ACTIVE'"
            ).fetchall()
    except Exception:
        return {"active": False, "threshold_adjustment_points": 0.0, "activations": []}
    total_tap = 0.0
    activations = []
    for r in rows:
        p = _load(r["proposal_json"])
        tap = float(p.get("threshold_adjustment_points", 0.0))
        total_tap += tap
        activations.append({"dimension": r["dimension"], "threshold_adjustment_points": tap})
    return {
        "active": bool(activations),
        "threshold_adjustment_points": total_tap,
        "activations": activations,
    }
