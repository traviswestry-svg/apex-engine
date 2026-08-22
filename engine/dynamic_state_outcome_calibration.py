"""APEX 68.3 — Dynamic-State Outcome Calibration.

Persists frozen decision-time dynamic-state context beside the existing APEX
47 evidence ledger and computes advisory, outcome-linked calibration summaries.
It never mutates live thresholds, confidence, consensus weights, or execution.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

VERSION = "68.4.0"
SCHEMA_VERSION = "apex.dynamic_state_outcome_calibration.v2"
MIN_SAMPLE = 20


def _m(v: Any) -> Dict[str, Any]:
    return dict(v) if isinstance(v, Mapping) else {}


def _f(v: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _b(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    return str(v or "").strip().upper() in {"1", "TRUE", "YES", "Y", "ON"}


def _policy(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    direct = _m(snapshot.get("dynamic_state_policy"))
    if direct:
        return direct
    dq = _m(snapshot.get("decision_quality"))
    direct = _m(dq.get("dynamic_state_policy"))
    if direct:
        return direct
    conviction = _m(snapshot.get("conviction"))
    return _m(conviction.get("dynamic_state_policy"))


def _dynamic(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    direct = _m(snapshot.get("dynamic_state"))
    if direct:
        return direct
    dq = _m(snapshot.get("decision_quality"))
    return _m(dq.get("dynamic_state"))


def _alert_state(snapshot: Mapping[str, Any], policy: Mapping[str, Any]) -> str:
    dq = _m(snapshot.get("decision_quality"))
    aq = _m(dq.get("alert_quality"))
    return str(aq.get("state") or snapshot.get("alert_state") or policy.get("state") or "UNKNOWN").upper()


def extract_context(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Freeze only decision-time state used for later outcome attribution."""
    s = dict(snapshot or {})
    policy = _policy(s)
    ds = _dynamic(s)
    flow = _m(ds.get("flow_excitation")) or _m(s.get("flow_excitation"))
    gamma = _m(ds.get("gamma_path")) or _m(s.get("gamma_path"))
    term = _m(ds.get("gamma_term_structure")) or _m(s.get("gamma_term_structure"))
    residual = _m(ds.get("residual_pressure")) or _m(s.get("residual_pressure"))
    event = _m(ds.get("event_phase")) or _m(s.get("event_phase"))

    modifiers = policy.get("modifiers") if isinstance(policy.get("modifiers"), list) else []
    residual_opposes = any(_m(x).get("driver") == "residual_pressure" and _m(x).get("effect") == "OPPOSES" for x in modifiers)

    ief = _f(flow.get("independent_evidence_factor"))
    if ief is None:
        independence_bucket = "UNKNOWN"
    elif ief < 0.25:
        independence_bucket = "HIGHLY_REDUNDANT"
    elif ief < 0.50:
        independence_bucket = "PARTLY_REDUNDANT"
    elif ief < 0.80:
        independence_bucket = "MOSTLY_INDEPENDENT"
    else:
        independence_bucket = "INDEPENDENT"

    return {
        "schema_version": SCHEMA_VERSION,
        "policy_version": policy.get("version"),
        "policy_state": str(policy.get("state") or "UNKNOWN").upper(),
        "alert_state": _alert_state(s, policy),
        "threshold_adjustment_points": _f(policy.get("threshold_adjustment_points"), 0.0) or 0.0,
        "conviction_penalty_points": _f(policy.get("conviction_penalty_points"), 0.0) or 0.0,
        "consensus_penalty_points": _f(policy.get("consensus_penalty_points"), 0.0) or 0.0,
        "suppress_new_alerts": _b(policy.get("suppress_new_alerts")),
        "watch_only": _b(policy.get("watch_only")),
        "event_phase": str(event.get("phase") or "NORMAL").upper(),
        "event_name": event.get("event_name") or event.get("name"),
        "minutes_to_event": _f(event.get("minutes_to_event")),
        "gamma_term_divergence": _b(term.get("term_divergence")),
        "near_term_gamma_fragility": _b(term.get("near_term_fragility")),
        "gamma_immediate_regime": term.get("immediate_regime") or gamma.get("current_regime"),
        "gamma_path_version": gamma.get("path_version"),
        "gamma_level_version": gamma.get("level_version"),
        "residual_pressure_unresolved": _b(residual.get("unresolved")),
        "residual_pressure_direction": residual.get("direction"),
        "residual_pressure_remaining": _f(residual.get("remaining_pressure")),
        "residual_pressure_opposes": residual_opposes,
        "flow_independent_evidence_factor": ief,
        "flow_independence_bucket": independence_bucket,
        "warnings": list(policy.get("warnings") or []),
        "blocking_conditions": list(policy.get("blocking_conditions") or []),
    }


def ensure_schema(conn) -> None:
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS dynamic_state_decision_context(
        decision_id TEXT PRIMARY KEY,
        captured_at TEXT NOT NULL,
        schema_version TEXT NOT NULL,
        policy_version TEXT,
        policy_state TEXT,
        alert_state TEXT,
        event_phase TEXT,
        gamma_term_divergence INTEGER NOT NULL DEFAULT 0,
        near_term_gamma_fragility INTEGER NOT NULL DEFAULT 0,
        residual_pressure_opposes INTEGER NOT NULL DEFAULT 0,
        flow_independence_bucket TEXT,
        threshold_adjustment_points REAL,
        conviction_penalty_points REAL,
        consensus_penalty_points REAL,
        context_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_dynamic_context_event ON dynamic_state_decision_context(event_phase);
    CREATE INDEX IF NOT EXISTS idx_dynamic_context_gamma ON dynamic_state_decision_context(gamma_term_divergence);
    CREATE INDEX IF NOT EXISTS idx_dynamic_context_residual ON dynamic_state_decision_context(residual_pressure_opposes);
    CREATE INDEX IF NOT EXISTS idx_dynamic_context_flow ON dynamic_state_decision_context(flow_independence_bucket);
    CREATE INDEX IF NOT EXISTS idx_dynamic_context_alert ON dynamic_state_decision_context(alert_state);
    ''')


def persist_context(conn, decision_id: str, captured_at: str, snapshot: Mapping[str, Any]) -> bool:
    ensure_schema(conn)
    ctx = extract_context(snapshot)
    conn.execute(
        """INSERT OR IGNORE INTO dynamic_state_decision_context(
        decision_id,captured_at,schema_version,policy_version,policy_state,alert_state,event_phase,
        gamma_term_divergence,near_term_gamma_fragility,residual_pressure_opposes,flow_independence_bucket,
        threshold_adjustment_points,conviction_penalty_points,consensus_penalty_points,context_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            decision_id, captured_at, SCHEMA_VERSION, ctx.get("policy_version"), ctx.get("policy_state"),
            ctx.get("alert_state"), ctx.get("event_phase"), int(ctx.get("gamma_term_divergence", False)),
            int(ctx.get("near_term_gamma_fragility", False)), int(ctx.get("residual_pressure_opposes", False)),
            ctx.get("flow_independence_bucket"), ctx.get("threshold_adjustment_points"),
            ctx.get("conviction_penalty_points"), ctx.get("consensus_penalty_points"), json.dumps(ctx, default=str),
        ),
    )
    return conn.total_changes > 0


def _aggregate(conn, field: str, min_sample: int) -> list[Dict[str, Any]]:
    allowed = {
        "event_phase", "gamma_term_divergence", "near_term_gamma_fragility",
        "residual_pressure_opposes", "flow_independence_bucket", "alert_state", "policy_state",
    }
    if field not in allowed:
        raise ValueError("unsupported calibration dimension")
    rows = conn.execute(
        f"""SELECT c.{field} bucket, g.outcome_json
            FROM dynamic_state_decision_context c
            JOIN grading_results g ON g.decision_id=c.decision_id
            WHERE g.status='GRADED'"""
    ).fetchall()
    buckets: Dict[str, list[Dict[str, Any]]] = {}
    for r in rows:
        key = str(r["bucket"] if r["bucket"] is not None else "UNKNOWN")
        try:
            outcome = json.loads(r["outcome_json"] or "{}")
        except Exception:
            outcome = {}
        buckets.setdefault(key, []).append(outcome)

    out = []
    for key, vals in sorted(buckets.items()):
        n = len(vals)
        wins = sum(1 for x in vals if _b(x.get("won") or x.get("direction_correct")))
        moves = [_f(x.get("directional_move")) for x in vals]
        mfes = [_f(x.get("mfe")) for x in vals]
        maes = [_f(x.get("mae")) for x in vals]
        moves = [x for x in moves if x is not None]
        mfes = [x for x in mfes if x is not None]
        maes = [x for x in maes if x is not None]
        try:
            from .dynamic_state_calibration_governance import wilson_interval
            ci = wilson_interval(float(wins), float(n))
        except Exception:
            ci = {"lower_pct": None, "upper_pct": None}
        out.append({
            "bucket": key,
            "sample_size": n,
            "calibration_ready": n >= min_sample,
            "win_rate_pct": round(100.0 * wins / n, 2) if n else None,
            "win_rate_confidence_interval_95": ci,
            "avg_directional_move": round(sum(moves) / len(moves), 4) if moves else None,
            "avg_mfe": round(sum(mfes) / len(mfes), 4) if mfes else None,
            "avg_mae": round(sum(maes) / len(maes), 4) if maes else None,
        })
    return out


def calibration_summary(path: str | Path, min_sample: int = MIN_SAMPLE) -> Dict[str, Any]:
    from .evidence_pipeline import _connect
    with _connect(path) as conn:
        ensure_schema(conn)
        context_count = conn.execute("SELECT COUNT(*) n FROM dynamic_state_decision_context").fetchone()["n"]
        graded_joined = conn.execute(
            """SELECT COUNT(*) n FROM dynamic_state_decision_context c
               JOIN grading_results g ON g.decision_id=c.decision_id WHERE g.status='GRADED'"""
        ).fetchone()["n"]
        dimensions = {
            name: _aggregate(conn, name, min_sample) for name in (
                "event_phase", "gamma_term_divergence", "near_term_gamma_fragility",
                "residual_pressure_opposes", "flow_independence_bucket", "alert_state",
            )
        }
    return {
        "ok": True,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "status": "READY" if graded_joined >= min_sample else "COLLECTING",
        "minimum_sample_per_bucket": min_sample,
        "decision_contexts": context_count,
        "graded_contexts": graded_joined,
        "dimensions": dimensions,
        "governance": {
            "advisory_only": True,
            "automatic_threshold_mutation": False,
            "automatic_confidence_mutation": False,
            "automatic_consensus_weight_mutation": False,
            "human_approval_required_for_policy_change": True,
            "decision_time_context_is_immutable": True,
            "promotion_governance_version": "68.4.0",
            "promotion_lifecycle": ["COLLECTING", "ELIGIBLE_FOR_REVIEW", "APPROVED", "REJECTED"],
            "production_handoff_required": True,
        },
    }
