"""APEX 68.3 — Dynamic-State Outcome Calibration.

Persists frozen decision-time dynamic-state context beside the existing APEX
47 evidence ledger and computes advisory, outcome-linked calibration summaries.
It never mutates live thresholds, confidence, consensus weights, or execution.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

VERSION = "69.9.3"
SCHEMA_VERSION = "apex.dynamic_state_outcome_calibration.v3"
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


def _ido(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    return _m(snapshot.get("institutional_decision_object"))


def _policy(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Resolve the exact finalized dynamic-state policy from all canonical homes."""
    direct = _m(snapshot.get("dynamic_state_policy"))
    if direct:
        return direct
    dq = _m(snapshot.get("decision_quality"))
    direct = _m(dq.get("dynamic_state_policy"))
    if direct:
        return direct
    conviction = _m(snapshot.get("conviction"))
    direct = _m(conviction.get("dynamic_state_policy"))
    if direct:
        return direct
    ido = _ido(snapshot)
    conviction = _m(ido.get("conviction"))
    direct = _m(conviction.get("dynamic_state_policy"))
    if direct:
        return direct
    consensus = _m(ido.get("institutional_consensus") or ido.get("consensus"))
    return _m(consensus.get("dynamic_state_policy"))


def _dynamic(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    direct = _m(snapshot.get("dynamic_state"))
    if direct:
        return direct
    dq = _m(snapshot.get("decision_quality"))
    return _m(dq.get("dynamic_state"))


def _source_status(present: bool, value: Any) -> str:
    if not present:
        return "SOURCE_MISSING"
    if value is None or str(value).strip().upper() in {"", "UNKNOWN", "NONE", "NULL", "N/A", "UNAVAILABLE"}:
        return "NORMALIZED_UNKNOWN"
    return "SOURCE_PRESENT"


def _alert_state_with_source(snapshot: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[str, str, str]:
    dq = _m(snapshot.get("decision_quality"))
    aq = _m(dq.get("alert_quality"))
    if "state" in aq:
        value = str(aq.get("state") or "UNKNOWN").upper()
        return value, _source_status(True, value), "decision_quality.alert_quality.state"
    if "alert_state" in snapshot:
        value = str(snapshot.get("alert_state") or "UNKNOWN").upper()
        return value, _source_status(True, value), "snapshot.alert_state"
    if "state" in policy:
        value = str(policy.get("state") or "UNKNOWN").upper()
        return value, _source_status(True, value), "dynamic_state_policy.state"
    return "UNKNOWN", "SOURCE_MISSING", "unavailable"


def extract_context(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Freeze decision-time dynamic context with explicit source provenance.

    Missing booleans are represented as None in context_json rather than silently
    becoming False. Legacy SQL columns remain backward-compatible, while read-time
    calibration uses provenance-aware context_json/snapshot recovery.
    """
    s = dict(snapshot or {})
    policy = _policy(s)
    ds = _dynamic(s)
    flow = _m(ds.get("flow_excitation")) or _m(s.get("flow_excitation"))
    gamma = _m(ds.get("gamma_path")) or _m(s.get("gamma_path"))
    term = _m(ds.get("gamma_term_structure")) or _m(s.get("gamma_term_structure"))
    residual = _m(ds.get("residual_pressure")) or _m(s.get("residual_pressure"))
    event = _m(ds.get("event_phase")) or _m(s.get("event_phase"))

    modifiers_present = isinstance(policy.get("modifiers"), list)
    modifiers = policy.get("modifiers") if modifiers_present else []
    residual_opposes = (
        any(_m(x).get("driver") == "residual_pressure" and _m(x).get("effect") == "OPPOSES" for x in modifiers)
        if modifiers_present else None
    )

    flow_present = "independent_evidence_factor" in flow and flow.get("independent_evidence_factor") is not None
    ief = _f(flow.get("independent_evidence_factor")) if flow_present else None
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

    event_present = "phase" in event and event.get("phase") is not None
    event_phase = str(event.get("phase") or "UNKNOWN").upper()
    divergence_present = "term_divergence" in term and term.get("term_divergence") is not None
    fragility_present = "near_term_fragility" in term and term.get("near_term_fragility") is not None
    divergence = _b(term.get("term_divergence")) if divergence_present else None
    fragility = _b(term.get("near_term_fragility")) if fragility_present else None
    policy_state_present = "state" in policy
    policy_state = str(policy.get("state") or "UNKNOWN").upper()
    alert_state, alert_status, alert_source = _alert_state_with_source(s, policy)

    provenance = {
        "event_phase": {
            "status": _source_status(event_present, event_phase),
            "source": "dynamic_state.event_phase.phase | snapshot.event_phase.phase",
        },
        "gamma_term_divergence": {
            "status": _source_status(divergence_present, divergence),
            "source": "dynamic_state.gamma_term_structure.term_divergence | snapshot.gamma_term_structure.term_divergence",
        },
        "near_term_gamma_fragility": {
            "status": _source_status(fragility_present, fragility),
            "source": "dynamic_state.gamma_term_structure.near_term_fragility | snapshot.gamma_term_structure.near_term_fragility",
        },
        "residual_pressure_opposes": {
            "status": _source_status(modifiers_present, residual_opposes),
            "source": "dynamic_state_policy.modifiers[driver=residual_pressure].effect=OPPOSES",
        },
        "flow_independence_bucket": {
            "status": _source_status(flow_present, independence_bucket),
            "source": "dynamic_state.flow_excitation.independent_evidence_factor | snapshot.flow_excitation.independent_evidence_factor",
        },
        "alert_state": {
            "status": alert_status,
            "source": alert_source,
        },
        "policy_state": {
            "status": _source_status(policy_state_present, policy_state),
            "source": "dynamic_state_policy.state",
        },
    }

    return {
        "schema_version": "apex.dynamic_state_outcome_calibration.v3",
        "policy_version": policy.get("version"),
        "policy_state": policy_state,
        "alert_state": alert_state,
        "threshold_adjustment_points": _f(policy.get("threshold_adjustment_points"), 0.0) or 0.0,
        "conviction_penalty_points": _f(policy.get("conviction_penalty_points"), 0.0) or 0.0,
        "consensus_penalty_points": _f(policy.get("consensus_penalty_points"), 0.0) or 0.0,
        "suppress_new_alerts": _b(policy.get("suppress_new_alerts")) if "suppress_new_alerts" in policy else None,
        "watch_only": _b(policy.get("watch_only")) if "watch_only" in policy else None,
        "event_phase": event_phase,
        "event_name": event.get("event_name") or event.get("name"),
        "minutes_to_event": _f(event.get("minutes_to_event")),
        "gamma_term_divergence": divergence,
        "near_term_gamma_fragility": fragility,
        "gamma_immediate_regime": term.get("immediate_regime") or gamma.get("current_regime"),
        "gamma_path_version": gamma.get("path_version"),
        "gamma_level_version": gamma.get("level_version"),
        "residual_pressure_unresolved": _b(residual.get("unresolved")) if "unresolved" in residual else None,
        "residual_pressure_direction": residual.get("direction"),
        "residual_pressure_remaining": _f(residual.get("remaining_pressure")),
        "residual_pressure_opposes": residual_opposes,
        "flow_independent_evidence_factor": ief,
        "flow_independence_bucket": independence_bucket,
        "warnings": list(policy.get("warnings") or []),
        "blocking_conditions": list(policy.get("blocking_conditions") or []),
        "capture_provenance": provenance,
        "capture_integrity_version": "69.9.2",
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
            ctx.get("alert_state"), ctx.get("event_phase"), int(bool(ctx.get("gamma_term_divergence"))),
            int(bool(ctx.get("near_term_gamma_fragility"))), int(bool(ctx.get("residual_pressure_opposes"))),
            ctx.get("flow_independence_bucket"), ctx.get("threshold_adjustment_points"),
            ctx.get("conviction_penalty_points"), ctx.get("consensus_penalty_points"), json.dumps(ctx, default=str),
        ),
    )
    return conn.total_changes > 0


def _load_json(value: Any) -> Dict[str, Any]:
    try:
        parsed = json.loads(value or "{}") if not isinstance(value, Mapping) else dict(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _normalize_bucket_value(value: Any) -> str:
    if value is None:
        return "UNKNOWN"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(int(value)) if float(value).is_integer() else str(value)
    text = str(value).strip().upper()
    return text if text and text not in _UNKNOWN_SENTINELS else "UNKNOWN"


def _effective_context(stored_context: Mapping[str, Any],
                       snapshot: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Return provenance-aware context without inventing missing history."""
    stored = dict(stored_context or {})
    recovered = extract_context(snapshot or {}) if snapshot else {}
    result = dict(stored)
    stored_prov = _m(stored.get("capture_provenance"))
    recovered_prov = _m(recovered.get("capture_provenance"))
    result_prov: Dict[str, Any] = {}

    for field in _CONTEXT_PROVENANCE:
        rp = _m(recovered_prov.get(field))
        sp = _m(stored_prov.get(field))
        if rp.get("status") == "SOURCE_PRESENT":
            result[field] = recovered.get(field)
            result_prov[field] = {**rp, "recovered_from_snapshot": True}
        elif sp.get("status") == "SOURCE_PRESENT":
            result[field] = stored.get(field)
            result_prov[field] = sp
        else:
            # Legacy rows often normalized missing booleans to False. If neither
            # the canonical snapshot nor stored provenance proves a source value,
            # keep the calibration bucket explicitly UNKNOWN.
            result[field] = None if field in {
                "gamma_term_divergence", "near_term_gamma_fragility", "residual_pressure_opposes"
            } else "UNKNOWN"
            source = rp.get("source") or sp.get("source") or _CONTEXT_PROVENANCE[field]
            result_prov[field] = {
                "status": rp.get("status") or sp.get("status") or "SOURCE_MISSING",
                "source": source,
                "recovered_from_snapshot": False,
            }
    result["capture_provenance"] = result_prov
    return result


def _joined_context_rows(conn, *, graded_only: bool = True):
    has_decisions = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='decisions'"
    ).fetchone()
    grade_filter = "WHERE g.status='GRADED'" if graded_only else ""
    if has_decisions:
        return conn.execute(
            f"""SELECT c.context_json,d.snapshot_json,g.outcome_json,c.decision_id
                FROM dynamic_state_decision_context c
                JOIN grading_results g ON g.decision_id=c.decision_id
                LEFT JOIN decisions d ON d.decision_id=c.decision_id
                {grade_filter}"""
        ).fetchall()
    return conn.execute(
        f"""SELECT c.context_json,NULL snapshot_json,g.outcome_json,c.decision_id
            FROM dynamic_state_decision_context c
            JOIN grading_results g ON g.decision_id=c.decision_id
            {grade_filter}"""
    ).fetchall()


def _aggregate(conn, field: str, min_sample: int) -> list[Dict[str, Any]]:
    allowed = set(_CONTEXT_PROVENANCE)
    if field not in allowed:
        raise ValueError("unsupported calibration dimension")
    rows = _joined_context_rows(conn, graded_only=True)
    buckets: Dict[str, list[Dict[str, Any]]] = {}
    source_present: Dict[str, int] = {}
    for r in rows:
        stored = _load_json(r["context_json"])
        snapshot = _load_json(r["snapshot_json"]) if r["snapshot_json"] else None
        ctx = _effective_context(stored, snapshot)
        key = _normalize_bucket_value(ctx.get(field))
        prov = _m(_m(ctx.get("capture_provenance")).get(field))
        if prov.get("status") == "SOURCE_PRESENT":
            source_present[key] = source_present.get(key, 0) + 1
        outcome = _load_json(r["outcome_json"])
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
        source_n = source_present.get(key, 0)
        calibration_ready = key != "UNKNOWN" and source_n >= min_sample
        out.append({
            "bucket": key,
            "sample_size": n,
            "source_present_sample_size": source_n,
            "calibration_ready": calibration_ready,
            "calibration_ready_reason": (
                "SOURCE_PRESENT_MINIMUM_MET" if calibration_ready else
                "SOURCE_MISSING_OR_UNKNOWN" if key == "UNKNOWN" else
                "MINIMUM_SOURCE_PRESENT_SAMPLE_NOT_MET"
            ),
            "win_rate_pct": round(100.0 * wins / n, 2) if n else None,
            "win_rate_confidence_interval_95": ci,
            "avg_directional_move": round(sum(moves) / len(moves), 4) if moves else None,
            "avg_mfe": round(sum(mfes) / len(mfes), 4) if mfes else None,
            "avg_mae": round(sum(maes) / len(maes), 4) if maes else None,
        })
    return out


_CONTEXT_PROVENANCE = {
    "event_phase": "dynamic_state.event_phase.phase | snapshot.event_phase.phase",
    "gamma_term_divergence": "dynamic_state.gamma_term_structure.term_divergence | snapshot.gamma_term_structure.term_divergence",
    "near_term_gamma_fragility": "dynamic_state.gamma_term_structure.near_term_fragility | snapshot.gamma_term_structure.near_term_fragility",
    "residual_pressure_opposes": "dynamic_state_policy.modifiers[driver=residual_pressure].effect=OPPOSES",
    "flow_independence_bucket": "dynamic_state.flow_excitation.independent_evidence_factor | snapshot.flow_excitation.independent_evidence_factor",
    "alert_state": "decision_quality.alert_quality.state | snapshot.alert_state | dynamic_state_policy.state",
    "policy_state": "dynamic_state_policy.state",
}

_UNKNOWN_SENTINELS = {"", "UNKNOWN", "NONE", "NULL", "N/A", "UNAVAILABLE"}


def _context_rows_for_audit(conn):
    has_decisions = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='decisions'"
    ).fetchone()
    if has_decisions:
        return conn.execute(
            """SELECT c.decision_id,c.context_json,d.snapshot_json
               FROM dynamic_state_decision_context c
               JOIN grading_results g ON g.decision_id=c.decision_id
               LEFT JOIN decisions d ON d.decision_id=c.decision_id
               WHERE g.status='GRADED'"""
        ).fetchall()
    return conn.execute(
        """SELECT c.decision_id,c.context_json,NULL snapshot_json
           FROM dynamic_state_decision_context c
           JOIN grading_results g ON g.decision_id=c.decision_id
           WHERE g.status='GRADED'"""
    ).fetchall()


def context_backfill(path: str | Path, *, apply: bool = False) -> Dict[str, Any]:
    """Recover historical context only when canonical snapshot source data exists.

    By default this is a preview. `apply=True` updates only fields whose snapshot
    provenance is SOURCE_PRESENT; missing historical source data is never inferred.
    """
    from .evidence_pipeline import _connect
    recoverable_decisions = 0
    recoverable_fields = 0
    applied_updates = 0
    skipped_source_missing = 0
    examples = []
    with _connect(path) as conn:
        ensure_schema(conn)
        has_decisions = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='decisions'"
        ).fetchone()
        if not has_decisions:
            return {
                "ok": True, "status": "NO_CANONICAL_SNAPSHOTS", "apply": bool(apply),
                "recoverable_decisions": 0, "recoverable_fields": 0, "applied_updates": 0,
                "skipped_source_missing": 0, "production_effect": "NONE",
                "execution_authority": False,
            }
        rows = conn.execute(
            """SELECT c.decision_id,c.context_json,d.snapshot_json
               FROM dynamic_state_decision_context c
               JOIN decisions d ON d.decision_id=c.decision_id"""
        ).fetchall()
        for row in rows:
            stored = _load_json(row["context_json"])
            snapshot = _load_json(row["snapshot_json"])
            recovered = extract_context(snapshot)
            recovered_prov = _m(recovered.get("capture_provenance"))
            changes: Dict[str, Any] = {}
            for field in _CONTEXT_PROVENANCE:
                prov = _m(recovered_prov.get(field))
                if prov.get("status") != "SOURCE_PRESENT":
                    skipped_source_missing += 1
                    continue
                recoverable_fields += 1
                if stored.get(field) != recovered.get(field) or _m(_m(stored.get("capture_provenance")).get(field)).get("status") != "SOURCE_PRESENT":
                    changes[field] = recovered.get(field)
            if not changes:
                continue
            recoverable_decisions += 1
            if len(examples) < 10:
                examples.append({"decision_id": row["decision_id"], "fields": sorted(changes)})
            if apply:
                merged = dict(stored)
                merged.update(changes)
                merged["capture_provenance"] = recovered.get("capture_provenance") or {}
                merged["capture_integrity_version"] = "69.9.2"
                sql_values = {
                    "policy_state": merged.get("policy_state"),
                    "alert_state": merged.get("alert_state"),
                    "event_phase": merged.get("event_phase"),
                    "gamma_term_divergence": int(bool(merged.get("gamma_term_divergence"))),
                    "near_term_gamma_fragility": int(bool(merged.get("near_term_gamma_fragility"))),
                    "residual_pressure_opposes": int(bool(merged.get("residual_pressure_opposes"))),
                    "flow_independence_bucket": merged.get("flow_independence_bucket"),
                }
                conn.execute(
                    """UPDATE dynamic_state_decision_context SET
                       policy_state=?,alert_state=?,event_phase=?,gamma_term_divergence=?,
                       near_term_gamma_fragility=?,residual_pressure_opposes=?,
                       flow_independence_bucket=?,context_json=? WHERE decision_id=?""",
                    (
                        sql_values["policy_state"], sql_values["alert_state"], sql_values["event_phase"],
                        sql_values["gamma_term_divergence"], sql_values["near_term_gamma_fragility"],
                        sql_values["residual_pressure_opposes"], sql_values["flow_independence_bucket"],
                        json.dumps(merged, default=str), row["decision_id"],
                    ),
                )
                applied_updates += 1
    return {
        "ok": True, "status": "APPLIED" if apply else "PREVIEW",
        "apply": bool(apply), "recoverable_decisions": recoverable_decisions,
        "recoverable_fields": recoverable_fields, "applied_updates": applied_updates,
        "skipped_source_missing": skipped_source_missing, "examples": examples,
        "missing_sources_never_inferred": True,
        "production_effect": "NONE", "execution_authority": False,
    }


def context_diversity_audit(path: str | Path) -> Dict[str, Any]:
    """Audit whether governed calibration context is informative and trustworthy."""
    from .calibration_activation import _read_availability
    from .canonical_persistence import connection as canonical_connection
    availability = _read_availability(path)
    base = {
        "ok": True, "version": VERSION,
        "schema_version": "apex.calibration_context_diversity.v3",
        "execution_authority": False, "production_effect": "NONE",
        "automatic_policy_mutation": False,
    }
    if availability["status"] == "MISSING_DB":
        return {**base, **availability, "graded_contexts": 0, "fields": {},
                "context_quality_deficient": False}
    try:
        with canonical_connection(path, read_only=True, timeout=0.35, wal=False, heal=False, busy_timeout_ms=250) as conn:
            has_ctx = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dynamic_state_decision_context'"
            ).fetchone()
            has_grades = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='grading_results'"
            ).fetchone()
            if not has_ctx or not has_grades:
                return {**base, "status": "EMPTY_NOT_INITIALIZED", "read_available": True,
                        "initialized": bool(has_ctx), "graded_contexts": 0, "fields": {},
                        "context_quality_deficient": False}
            rows = _context_rows_for_audit(conn)
    except Exception as exc:
        return {**base, **_read_availability(path, exc), "graded_contexts": 0,
                "fields": {}, "context_quality_deficient": False}

    fields: Dict[str, Any] = {}
    for field, provenance in _CONTEXT_PROVENANCE.items():
        vals = []
        status_counts: Dict[str, int] = {}
        for row in rows:
            stored = _load_json(row["context_json"])
            snapshot = _load_json(row["snapshot_json"]) if row["snapshot_json"] else None
            ctx = _effective_context(stored, snapshot)
            normalized = _normalize_bucket_value(ctx.get(field))
            vals.append(normalized)
            prov = _m(_m(ctx.get("capture_provenance")).get(field))
            status = str(prov.get("status") or "SOURCE_MISSING")
            status_counts[status] = status_counts.get(status, 0) + 1
        unknown = [v for v in vals if v == "UNKNOWN"]
        known = [v for v in vals if v != "UNKNOWN"]
        distinct_known = sorted(set(known))
        if not vals:
            state = "AVAILABLE"
        elif not known:
            state = "UNKNOWN"
        elif len(distinct_known) == 1:
            state = "CONSTANT"
        else:
            state = "VARIABLE"
        counts: Dict[str, int] = {}
        for value in vals:
            counts[value] = counts.get(value, 0) + 1
        fields[field] = {
            "state": state,
            "provenance": provenance,
            "sample_size": len(vals),
            "unknown_count": len(unknown),
            "unknown_pct": round(100.0 * len(unknown) / len(vals), 2) if vals else None,
            "distinct_known_values": len(distinct_known),
            "values": counts,
            "capture_status_counts": status_counts,
            "source_present_count": status_counts.get("SOURCE_PRESENT", 0),
            "source_present_pct": round(100.0 * status_counts.get("SOURCE_PRESENT", 0) / len(vals), 2) if vals else None,
            "source_missing_count": status_counts.get("SOURCE_MISSING", 0),
            "normalized_unknown_count": status_counts.get("NORMALIZED_UNKNOWN", 0),
        }

    variable_count = sum(1 for x in fields.values() if x["state"] == "VARIABLE")
    unknown_count = sum(1 for x in fields.values() if x["state"] == "UNKNOWN")
    constant_count = sum(1 for x in fields.values() if x["state"] == "CONSTANT")
    graded = len(rows)
    complete_coverage_fields = sum(1 for x in fields.values() if graded > 0 and x["source_present_count"] == graded)
    partial_coverage_fields = sum(1 for x in fields.values() if 0 < x["source_present_count"] < graded)
    missing_coverage_fields = sum(1 for x in fields.values() if graded > 0 and x["source_present_count"] == 0)
    coverage_complete = bool(graded > 0 and complete_coverage_fields == len(fields))
    deficient = bool(graded >= MIN_SAMPLE and variable_count == 0)
    partial_recovery = bool(graded >= MIN_SAMPLE and variable_count > 0 and not coverage_complete)
    if deficient:
        quality_state = "CONTEXT_QUALITY_DEFICIENT"
        quality_reason = "Aggregate graded history is sufficient, but no governed calibration field varies across source-verified graded contexts."
    elif partial_recovery:
        quality_state = "PARTIAL_CONTEXT_RECOVERY"
        quality_reason = "Source-verified context variation exists, but historical coverage remains incomplete across governed calibration fields."
    else:
        quality_state = "CONTEXT_DIVERSITY_PRESENT"
        quality_reason = "Source-verified governed calibration context varies and coverage is complete for the audited fields."
    recoverable = None
    try:
        recoverable = context_backfill(path, apply=False)
    except Exception as exc:
        recoverable = {"ok": False, "status": "DEGRADED", "error": f"{type(exc).__name__}: {exc}"}
    return {
        **base, "status": "READY", "read_available": True, "initialized": True,
        "graded_contexts": graded, "fields": fields,
        "variable_field_count": variable_count, "constant_field_count": constant_count,
        "unknown_field_count": unknown_count,
        "complete_coverage_field_count": complete_coverage_fields,
        "partial_coverage_field_count": partial_coverage_fields,
        "missing_coverage_field_count": missing_coverage_fields,
        "audited_field_count": len(fields),
        "context_coverage_complete": coverage_complete,
        "context_coverage_partial": partial_recovery,
        "context_quality_deficient": deficient,
        "quality_state": quality_state,
        "historical_backfill_preview": recoverable,
        "reason": quality_reason,
    }



def calibration_summary(path: str | Path, min_sample: int = MIN_SAMPLE) -> Dict[str, Any]:
    """Read-only calibration summary with bounded, truthful availability."""
    from .calibration_activation import _read_availability
    from .canonical_persistence import connection as canonical_connection
    availability = _read_availability(path)
    if availability["status"] == "MISSING_DB":
        return {
            "ok": True, "version": VERSION, "schema_version": SCHEMA_VERSION,
            **availability, "minimum_sample_per_bucket": min_sample,
            "decision_contexts": 0, "graded_contexts": 0, "dimensions": {},
            "execution_authority": False,
        }
    try:
        with canonical_connection(path, read_only=True, timeout=0.35, wal=False, heal=False, busy_timeout_ms=250) as conn:
            has_ctx = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dynamic_state_decision_context'"
            ).fetchone()
            has_grades = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='grading_results'"
            ).fetchone()
            if not has_ctx:
                context_count, graded_joined = 0, 0
                dimensions = {name: [] for name in (
                    "event_phase", "gamma_term_divergence", "near_term_gamma_fragility",
                    "residual_pressure_opposes", "flow_independence_bucket", "alert_state", "policy_state",
                )}
            else:
                context_count = conn.execute("SELECT COUNT(*) n FROM dynamic_state_decision_context").fetchone()["n"]
                graded_joined = conn.execute(
                    """SELECT COUNT(*) n FROM dynamic_state_decision_context c
                       JOIN grading_results g ON g.decision_id=c.decision_id WHERE g.status='GRADED'"""
                ).fetchone()["n"] if has_grades else 0
                dimensions = {
                    name: (_aggregate(conn, name, min_sample) if has_grades else []) for name in (
                        "event_phase", "gamma_term_divergence", "near_term_gamma_fragility",
                        "residual_pressure_opposes", "flow_independence_bucket", "alert_state", "policy_state",
                    )
                }
    except Exception as exc:
        return {
            "ok": False, "version": VERSION, "schema_version": SCHEMA_VERSION,
            **_read_availability(path, exc), "minimum_sample_per_bucket": min_sample,
            "decision_contexts": 0, "graded_contexts": 0, "dimensions": {},
            "execution_authority": False,
        }
    ready_bucket_count = sum(
        1 for buckets in dimensions.values() for bucket in buckets if bucket.get("calibration_ready")
    )
    if graded_joined < min_sample:
        summary_status = "COLLECTING"
    elif ready_bucket_count == 0:
        summary_status = "CONTEXT_QUALITY_DEFICIENT"
    else:
        summary_status = "READY"
    return {
        "ok": True,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "status": summary_status,
        "read_available": True, "initialized": True, "degraded": False,
        "minimum_sample_per_bucket": min_sample,
        "decision_contexts": context_count,
        "graded_contexts": graded_joined,
        "source_verified_ready_bucket_count": ready_bucket_count,
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
