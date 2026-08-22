"""APEX 68.4 — Dynamic-State Calibration Integrity & Promotion Governance.

Adds statistical integrity and a governed recommendation lifecycle on top of the
68.3 immutable decision/outcome calibration ledger. This module is advisory:
APPROVED means approved as a calibration recommendation only. It cannot mutate
live policy and must hand off to the repository's production governance boundary.
"""
from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

VERSION = "68.4.0"
SCHEMA_VERSION = "apex.dynamic_state_calibration_governance.v1"
DEFAULT_MIN_SAMPLE = 20
DEFAULT_MIN_EFFECTIVE_SAMPLE = 15.0
DEFAULT_MIN_DELTA_PP = 5.0
DEFAULT_MAX_P_VALUE = 0.10
ALLOWED_STATES = ("COLLECTING", "ELIGIBLE_FOR_REVIEW", "APPROVED", "REJECTED")
ALLOWED_DIMENSIONS = {
    "event_phase", "gamma_term_divergence", "near_term_gamma_fragility",
    "residual_pressure_opposes", "flow_independence_bucket", "alert_state", "policy_state",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(v: Any) -> Dict[str, Any]:
    try:
        x = json.loads(v or "{}") if not isinstance(v, Mapping) else dict(v)
        return x if isinstance(x, dict) else {}
    except Exception:
        return {}


def _b(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    return str(v or "").strip().upper() in {"1", "TRUE", "YES", "Y", "ON"}


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _independence_weight(context: Mapping[str, Any]) -> float:
    raw = context.get("flow_independent_evidence_factor")
    if raw is not None:
        return max(0.0, min(1.0, _f(raw, 0.0)))
    bucket = str(context.get("flow_independence_bucket") or "UNKNOWN").upper()
    return {
        "HIGHLY_REDUNDANT": 0.20,
        "PARTLY_REDUNDANT": 0.40,
        "MOSTLY_INDEPENDENT": 0.70,
        "INDEPENDENT": 1.00,
        "UNKNOWN": 0.50,
    }.get(bucket, 0.50)


def wilson_interval(successes: float, n: float, z: float = 1.959963984540054) -> Dict[str, Optional[float]]:
    """Wilson score interval; supports effective (fractional) sample counts."""
    if n <= 0:
        return {"lower_pct": None, "upper_pct": None}
    p = max(0.0, min(1.0, successes / n))
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2.0 * n)) / denom
    margin = (z / denom) * math.sqrt(max(0.0, p * (1.0 - p) / n + z2 / (4.0 * n * n)))
    return {
        "lower_pct": round(max(0.0, centre - margin) * 100.0, 2),
        "upper_pct": round(min(1.0, centre + margin) * 100.0, 2),
    }


def _two_prop_p_value(s1: float, n1: float, s2: float, n2: float) -> Optional[float]:
    if n1 <= 0 or n2 <= 0:
        return None
    p1, p2 = s1 / n1, s2 / n2
    pooled = (s1 + s2) / (n1 + n2)
    se = math.sqrt(max(0.0, pooled * (1.0 - pooled) * (1.0 / n1 + 1.0 / n2)))
    if se <= 0:
        return 1.0 if abs(p1 - p2) < 1e-12 else 0.0
    z = abs(p1 - p2) / se
    return max(0.0, min(1.0, math.erfc(z / math.sqrt(2.0))))


def ensure_schema(conn) -> None:
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS dynamic_calibration_candidates(
        candidate_id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        dimension TEXT NOT NULL,
        challenger_bucket TEXT NOT NULL,
        incumbent_bucket TEXT NOT NULL,
        expected_relation TEXT NOT NULL,
        proposal_json TEXT NOT NULL,
        thresholds_json TEXT NOT NULL,
        status TEXT NOT NULL,
        last_assessed_at TEXT,
        assessment_json TEXT,
        approved_at TEXT,
        approved_by TEXT,
        rejection_reason TEXT,
        integrity_hash TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_dynamic_candidate_status ON dynamic_calibration_candidates(status,created_at);
    CREATE TABLE IF NOT EXISTS dynamic_calibration_reviews(
        review_id TEXT PRIMARY KEY,
        candidate_id TEXT NOT NULL,
        reviewed_at TEXT NOT NULL,
        actor TEXT NOT NULL,
        decision TEXT NOT NULL,
        note TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        FOREIGN KEY(candidate_id) REFERENCES dynamic_calibration_candidates(candidate_id)
    );
    CREATE INDEX IF NOT EXISTS idx_dynamic_review_candidate ON dynamic_calibration_reviews(candidate_id,reviewed_at);
    ''')


def _integrity_hash(payload: Mapping[str, Any]) -> str:
    import hashlib
    raw = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _bucket_stats(conn, dimension: str, bucket: str) -> Dict[str, Any]:
    if dimension not in ALLOWED_DIMENSIONS:
        raise ValueError("unsupported calibration dimension")
    rows = conn.execute(
        f'''SELECT c.context_json,g.outcome_json
            FROM dynamic_state_decision_context c
            JOIN grading_results g ON g.decision_id=c.decision_id
            WHERE g.status='GRADED' AND CAST(c.{dimension} AS TEXT)=?''',
        (str(bucket),),
    ).fetchall()
    raw_n = len(rows)
    weighted_n = 0.0
    weighted_wins = 0.0
    raw_wins = 0
    for row in rows:
        ctx = _load(row["context_json"])
        out = _load(row["outcome_json"])
        won = _b(out.get("won") or out.get("direction_correct"))
        w = _independence_weight(ctx)
        weighted_n += w
        weighted_wins += w * (1.0 if won else 0.0)
        raw_wins += int(won)
    rate = (weighted_wins / weighted_n) if weighted_n > 0 else None
    ci = wilson_interval(weighted_wins, weighted_n)
    return {
        "bucket": str(bucket),
        "raw_sample_size": raw_n,
        "raw_wins": raw_wins,
        "effective_sample_size": round(weighted_n, 3),
        "effective_wins": round(weighted_wins, 3),
        "independence_discount_pct": round(100.0 * (1.0 - weighted_n / raw_n), 2) if raw_n else None,
        "weighted_win_rate_pct": round(rate * 100.0, 2) if rate is not None else None,
        "confidence_interval_95": ci,
    }


def compare_buckets(path: str | Path, dimension: str, challenger_bucket: str, incumbent_bucket: str, *,
                    expected_relation: str = "LOWER", min_sample: int = DEFAULT_MIN_SAMPLE,
                    min_effective_sample: float = DEFAULT_MIN_EFFECTIVE_SAMPLE,
                    min_delta_pp: float = DEFAULT_MIN_DELTA_PP,
                    max_p_value: float = DEFAULT_MAX_P_VALUE) -> Dict[str, Any]:
    from .evidence_pipeline import _connect
    relation = str(expected_relation or "LOWER").upper()
    if relation not in {"LOWER", "HIGHER", "DIFFERENT"}:
        raise ValueError("expected_relation must be LOWER, HIGHER, or DIFFERENT")
    with _connect(path) as conn:
        from .dynamic_state_outcome_calibration import ensure_schema as ensure_context_schema
        ensure_context_schema(conn)
        ch = _bucket_stats(conn, dimension, challenger_bucket)
        inc = _bucket_stats(conn, dimension, incumbent_bucket)
    ch_rate = ch.get("weighted_win_rate_pct")
    inc_rate = inc.get("weighted_win_rate_pct")
    delta = (ch_rate - inc_rate) if ch_rate is not None and inc_rate is not None else None
    p_value = _two_prop_p_value(ch["effective_wins"], ch["effective_sample_size"], inc["effective_wins"], inc["effective_sample_size"])
    sample_ok = ch["raw_sample_size"] >= min_sample and inc["raw_sample_size"] >= min_sample
    effective_ok = ch["effective_sample_size"] >= min_effective_sample and inc["effective_sample_size"] >= min_effective_sample
    magnitude_ok = delta is not None and abs(delta) >= min_delta_pp
    significance_ok = p_value is not None and p_value <= max_p_value
    relation_ok = delta is not None and (
        (relation == "LOWER" and delta < 0) or
        (relation == "HIGHER" and delta > 0) or
        relation == "DIFFERENT"
    )
    eligible = all((sample_ok, effective_ok, magnitude_ok, significance_ok, relation_ok))
    blockers = []
    if not sample_ok: blockers.append("MINIMUM_RAW_SAMPLE_NOT_MET")
    if not effective_ok: blockers.append("MINIMUM_INDEPENDENT_EFFECTIVE_SAMPLE_NOT_MET")
    if not magnitude_ok: blockers.append("MINIMUM_EFFECT_DELTA_NOT_MET")
    if not significance_ok: blockers.append("STATISTICAL_SIGNIFICANCE_NOT_MET")
    if not relation_ok: blockers.append("EXPECTED_RELATION_NOT_SUPPORTED")
    return {
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "dimension": dimension,
        "challenger": ch,
        "incumbent": inc,
        "delta_win_rate_pp": round(delta, 2) if delta is not None else None,
        "two_sided_p_value": round(p_value, 6) if p_value is not None else None,
        "expected_relation": relation,
        "integrity_gates": {
            "raw_sample": sample_ok,
            "independent_effective_sample": effective_ok,
            "minimum_effect_delta": magnitude_ok,
            "statistical_significance": significance_ok,
            "expected_relation": relation_ok,
        },
        "thresholds": {
            "min_raw_sample_per_bucket": int(min_sample),
            "min_effective_sample_per_bucket": float(min_effective_sample),
            "min_delta_win_rate_pp": float(min_delta_pp),
            "max_two_sided_p_value": float(max_p_value),
        },
        "eligible_for_review": eligible,
        "blockers": blockers,
        "advisory_only": True,
        "production_effect": "NONE",
    }


def create_candidate(path: str | Path, *, dimension: str, challenger_bucket: str, incumbent_bucket: str,
                     proposal: Mapping[str, Any], expected_relation: str = "LOWER", actor: str = "SYSTEM",
                     min_sample: int = DEFAULT_MIN_SAMPLE, min_effective_sample: float = DEFAULT_MIN_EFFECTIVE_SAMPLE,
                     min_delta_pp: float = DEFAULT_MIN_DELTA_PP, max_p_value: float = DEFAULT_MAX_P_VALUE) -> Dict[str, Any]:
    from .evidence_pipeline import _connect
    if dimension not in ALLOWED_DIMENSIONS:
        raise ValueError("unsupported calibration dimension")
    cid = str(uuid.uuid4())
    created = _now()
    thresholds = {"min_sample": int(min_sample), "min_effective_sample": float(min_effective_sample),
                  "min_delta_pp": float(min_delta_pp), "max_p_value": float(max_p_value)}
    immutable = {"candidate_id": cid, "created_at": created, "dimension": dimension,
                 "challenger_bucket": str(challenger_bucket), "incumbent_bucket": str(incumbent_bucket),
                 "expected_relation": str(expected_relation).upper(), "proposal": dict(proposal), "thresholds": thresholds}
    h = _integrity_hash(immutable)
    with _connect(path) as conn:
        ensure_schema(conn)
        conn.execute('''INSERT INTO dynamic_calibration_candidates(
            candidate_id,created_at,created_by,dimension,challenger_bucket,incumbent_bucket,expected_relation,
            proposal_json,thresholds_json,status,integrity_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
            (cid, created, actor, dimension, str(challenger_bucket), str(incumbent_bucket), str(expected_relation).upper(),
             json.dumps(dict(proposal), sort_keys=True, default=str), json.dumps(thresholds, sort_keys=True), "COLLECTING", h))
    assessment = assess_candidate(path, cid)
    return {"ok": True, "candidate_id": cid, "status": assessment["status"], "assessment": assessment,
            "production_effect": "NONE", "automatic_promotion": False}


def _candidate(conn, candidate_id: str):
    return conn.execute("SELECT * FROM dynamic_calibration_candidates WHERE candidate_id=?", (candidate_id,)).fetchone()


def assess_candidate(path: str | Path, candidate_id: str) -> Dict[str, Any]:
    from .evidence_pipeline import _connect
    with _connect(path) as conn:
        ensure_schema(conn)
        row = _candidate(conn, candidate_id)
        if not row:
            return {"ok": False, "status": "UNAVAILABLE", "error": "candidate not found", "production_effect": "NONE"}
        thresholds = _load(row["thresholds_json"])
    comparison = compare_buckets(
        path, row["dimension"], row["challenger_bucket"], row["incumbent_bucket"],
        expected_relation=row["expected_relation"], min_sample=int(thresholds.get("min_sample", DEFAULT_MIN_SAMPLE)),
        min_effective_sample=_f(thresholds.get("min_effective_sample"), DEFAULT_MIN_EFFECTIVE_SAMPLE),
        min_delta_pp=_f(thresholds.get("min_delta_pp"), DEFAULT_MIN_DELTA_PP),
        max_p_value=_f(thresholds.get("max_p_value"), DEFAULT_MAX_P_VALUE),
    )
    current = str(row["status"])
    # Never auto-promote beyond review eligibility and never undo terminal human decisions.
    if current in {"APPROVED", "REJECTED"}:
        new_status = current
    else:
        new_status = "ELIGIBLE_FOR_REVIEW" if comparison["eligible_for_review"] else "COLLECTING"
    assessed = _now()
    with _connect(path) as conn:
        ensure_schema(conn)
        conn.execute("UPDATE dynamic_calibration_candidates SET status=?,last_assessed_at=?,assessment_json=? WHERE candidate_id=?",
                     (new_status, assessed, json.dumps(comparison, sort_keys=True, default=str), candidate_id))
    return {"ok": True, "candidate_id": candidate_id, "status": new_status, "assessment": comparison,
            "automatic_promotion": False, "production_effect": "NONE"}


def review_candidate(path: str | Path, candidate_id: str, *, decision: str, actor: str, note: str = "",
                     evidence: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Human governance decision. APPROVED is recommendation approval, not production activation."""
    from .evidence_pipeline import _connect
    decision = str(decision).upper()
    if decision not in {"APPROVE", "REJECT"}:
        return {"ok": False, "status": "APPROVAL_REQUIRED", "error": "decision must be APPROVE or REJECT", "production_effect": "NONE"}
    if not str(actor or "").strip():
        return {"ok": False, "status": "APPROVAL_REQUIRED", "error": "actor is required", "production_effect": "NONE"}
    latest = assess_candidate(path, candidate_id)
    if not latest.get("ok"):
        return latest
    with _connect(path) as conn:
        ensure_schema(conn)
        row = _candidate(conn, candidate_id)
        current = str(row["status"])
        if current in {"APPROVED", "REJECTED"}:
            return {"ok": False, "status": current, "error": "candidate is already terminal", "production_effect": "NONE"}
        if decision == "APPROVE" and current != "ELIGIBLE_FOR_REVIEW":
            return {"ok": False, "status": current, "error": "integrity gates are not satisfied", "production_effect": "NONE"}
        new_status = "APPROVED" if decision == "APPROVE" else "REJECTED"
        at = _now()
        rid = str(uuid.uuid4())
        conn.execute("INSERT INTO dynamic_calibration_reviews VALUES(?,?,?,?,?,?,?)",
                     (rid, candidate_id, at, actor, decision, str(note or ""), json.dumps(dict(evidence or {}), sort_keys=True, default=str)))
        conn.execute("UPDATE dynamic_calibration_candidates SET status=?,approved_at=?,approved_by=?,rejection_reason=? WHERE candidate_id=?",
                     (new_status, at if new_status == "APPROVED" else None, actor if new_status == "APPROVED" else None,
                      str(note or "") if new_status == "REJECTED" else None, candidate_id))
    return {
        "ok": True, "candidate_id": candidate_id, "status": new_status,
        "handoff_required": new_status == "APPROVED",
        "handoff_target": "engine.calibration_activation" if new_status == "APPROVED" else None,
        "automatic_production_activation": False,
        "production_effect": "NONE",
    }


def governance_overview(path: str | Path, limit: int = 50) -> Dict[str, Any]:
    """Read-only governance snapshot for observability routes.

    Never creates schema or waits on the writer policy. Missing/unavailable stores
    are represented as an empty/degraded snapshot instead of blocking HTTP.
    """
    from .canonical_persistence import connection as canonical_connection
    candidates = []
    try:
        with canonical_connection(path, read_only=True, timeout=0.35, wal=False, heal=False, busy_timeout_ms=250) as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dynamic_calibration_candidates'"
            ).fetchone()
            rows = conn.execute(
                "SELECT * FROM dynamic_calibration_candidates ORDER BY created_at DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            ).fetchall() if exists else []
    except Exception as exc:
        return {
            "ok": False, "version": VERSION, "schema_version": SCHEMA_VERSION,
            "status": "READ_UNAVAILABLE", "lifecycle": list(ALLOWED_STATES),
            "counts": {state: 0 for state in ALLOWED_STATES}, "candidates": [],
            "degraded": True, "error": type(exc).__name__,
            "governance": {"automatic_promotion": False, "automatic_production_activation": False,
                           "approved_means_recommendation_only": True,
                           "production_handoff": "engine.calibration_activation",
                           "production_effect": "NONE"},
        }
    for r in rows:
        candidates.append({
            "candidate_id": r["candidate_id"], "created_at": r["created_at"], "dimension": r["dimension"],
            "challenger_bucket": r["challenger_bucket"], "incumbent_bucket": r["incumbent_bucket"],
            "expected_relation": r["expected_relation"], "status": r["status"],
            "proposal": _load(r["proposal_json"]), "assessment": _load(r["assessment_json"]),
            "integrity_hash": r["integrity_hash"], "approved_at": r["approved_at"], "approved_by": r["approved_by"],
        })
    counts = {state: sum(1 for c in candidates if c["status"] == state) for state in ALLOWED_STATES}
    return {
        "ok": True, "version": VERSION, "schema_version": SCHEMA_VERSION,
        "status": "READY", "degraded": False, "lifecycle": list(ALLOWED_STATES), "counts": counts, "candidates": candidates,
        "integrity": {
            "confidence_intervals": "WILSON_95",
            "comparison_test": "TWO_PROPORTION_Z_TWO_SIDED",
            "independence_adjustment": "FLOW_INDEPENDENT_EVIDENCE_WEIGHT",
            "minimum_independent_sample_enforced": True,
        },
        "governance": {
            "automatic_promotion": False,
            "automatic_production_activation": False,
            "approved_means_recommendation_only": True,
            "production_handoff": "engine.calibration_activation",
            "production_effect": "NONE",
        },
    }
