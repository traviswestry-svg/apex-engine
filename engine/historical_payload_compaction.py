"""APEX 69.10.10 — historical evidence payload dependency & compaction readiness.

Read-only diagnostics only.  This module never rewrites, deletes, VACUUMs, or
compacts canonical evidence.  It measures historical amplification, simulates
current bounded storage projections on a bounded sample (or an explicit
operator-requested exhaustive scan), and publishes source-verified dependency
contracts that must be satisfied before any future historical rewrite.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .evidence_pipeline import DEFAULT_DB as EVIDENCE_DB, _persisted_snapshot_projection
from .persistent_store import persistent_sqlite_path
from .trigger_observatory import _bounded_trigger_evidence

VERSION = "69.10.11"
SCHEMA_VERSION = "apex.historical_payload_compaction_readiness.v2"
TRIGGER_DB = persistent_sqlite_path("APEX_TRIGGER_OBSERVATORY_DB", "apex_trigger_observatory.db")
DEFAULT_SAMPLE_LIMIT = 50

# Source-verified consumers of the two historical payload columns.  These are
# deliberately conservative.  A future compaction build must either preserve
# these contracts or introduce an immutable archival/sidecar representation.
TRIGGER_EVIDENCE_DEPENDENCIES = {
    "payload_column": "observed_trade_triggers.evidence_json",
    "full_payload_consumers": [
        "engine.trigger_observatory.history",
    ],
    "field_consumers": {
        "engine.trigger_observatory.trade_visualization._premium_projection": [
            "contract", "option_contract", "contract_symbol",
            "entry_premium", "premium", "option_premium", "current_premium",
            "peak_premium", "max_premium", "target1_premium", "tp1_premium",
            "target2_premium", "tp2_premium", "target3_premium", "tp3_premium",
            "stop_premium", "pine",
        ],
    },
    "rewrite_blockers": [
        "history returns the persisted evidence payload to callers",
        "premium visualization reads persisted trigger evidence",
        "no immutable historical sidecar/archive exists for dropped payload fields",
    ],
}

DECISION_SNAPSHOT_DEPENDENCIES = {
    "payload_column": "decisions.snapshot_json",
    "field_consumers": {
        "engine.evidence_pipeline.readiness": [
            "eligibility_reason", "execution_actionable", "actionable", "observational_learning_eligible",
        ],
        "engine.outcome_grader": ["observational_only", "feature_vector"],
        "engine.trigger_observatory.predictive_validation": [
            "action", "execution_actionable", "actionable", "observational_learning_eligible",
            "apex_release_version", "deployment", "institutional_decision_object",
        ],
        "engine.dynamic_state_outcome_calibration": [
            "dynamic_state_policy", "decision_quality", "conviction", "institutional_decision_object",
            "dynamic_state", "flow_excitation", "gamma_path", "gamma_term_structure",
            "residual_pressure", "event_phase",
        ],
        "engine.decision_outcome_attribution": [
            "action", "decision_state", "state", "learning_eligible", "direction", "entry_reference",
            "entry_price", "ticker", "confidence", "entry_timing", "entry_quality",
        ],
        "engine.historical_evidence_lifecycle.actionability_capture_readiness": [
            "counterfactual_actionability", "apex_release_version", "version",
        ],
    },
    "rewrite_blockers": [
        "graded/calibration consumers still recover context from historical snapshot_json",
        "outcome/attribution consumers can read feature_vector and gate-like nested fields",
        "no immutable historical sidecar/archive exists for fields removed by a rewrite",
    ],
}


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, default=str, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _read_only(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    c = sqlite3.connect(uri, uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _project_rows(
    conn: sqlite3.Connection,
    *,
    table: str,
    id_column: str,
    time_column: str,
    payload_column: str,
    projector: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    sample_limit: int,
    exhaustive: bool,
) -> dict[str, Any]:
    aggregate = conn.execute(
        f"SELECT COUNT(*) n, COALESCE(SUM(LENGTH({payload_column})),0) total_bytes, "
        f"COALESCE(AVG(LENGTH({payload_column})),0) avg_bytes, COALESCE(MAX(LENGTH({payload_column})),0) max_bytes FROM {table}"
    ).fetchone()
    total_rows = int(aggregate["n"] or 0)
    limit = max(1, int(sample_limit or DEFAULT_SAMPLE_LIMIT))
    if exhaustive:
        sql = f"SELECT {id_column} row_id,{time_column} observed_at,{payload_column} payload,LENGTH({payload_column}) source_bytes FROM {table} ORDER BY {time_column}"
        params: tuple[Any, ...] = ()
    else:
        # Largest rows are the most relevant compaction candidates and make the
        # endpoint deterministic and bounded even when historical payloads are huge.
        sql = f"SELECT {id_column} row_id,{time_column} observed_at,{payload_column} payload,LENGTH({payload_column}) source_bytes FROM {table} ORDER BY LENGTH({payload_column}) DESC LIMIT ?"
        params = (limit,)
    rows_scanned = 0
    source_bytes_scanned = 0
    projected_bytes_scanned = 0
    projection_errors = 0
    unchanged_rows = 0
    row_examples: list[dict[str, Any]] = []
    for row in conn.execute(sql, params):
        rows_scanned += 1
        source_bytes = int(row["source_bytes"] or 0)
        source_bytes_scanned += source_bytes
        try:
            parsed = json.loads(row["payload"] or "{}")
            if not isinstance(parsed, Mapping):
                raise TypeError("payload is not a mapping")
            projected = dict(projector(parsed))
            projected_raw = _json_bytes(projected)
            projected_bytes = len(projected_raw)
            projected_bytes_scanned += projected_bytes
            if projected_bytes >= source_bytes:
                unchanged_rows += 1
            if len(row_examples) < 20:
                row_examples.append({
                    "row_id": str(row["row_id"]),
                    "observed_at": row["observed_at"],
                    "source_bytes": source_bytes,
                    "projected_bytes": projected_bytes,
                    "logical_reduction_bytes": max(0, source_bytes - projected_bytes),
                    "source_sha256": hashlib.sha256((row["payload"] or "").encode("utf-8")).hexdigest(),
                })
        except Exception as exc:
            projection_errors += 1
            if len(row_examples) < 20:
                row_examples.append({
                    "row_id": str(row["row_id"]),
                    "observed_at": row["observed_at"],
                    "source_bytes": source_bytes,
                    "projection_error": f"{type(exc).__name__}: {exc}",
                })
    logical_reduction = max(0, source_bytes_scanned - projected_bytes_scanned)
    ratio = (projected_bytes_scanned / source_bytes_scanned) if source_bytes_scanned else None
    projected_total_estimate = None
    logical_reduction_estimate = None
    if not exhaustive and source_bytes_scanned and rows_scanned:
        # This is explicitly a largest-row sample estimate, not an exact total.
        avg_ratio = ratio if ratio is not None else 1.0
        projected_total_estimate = int(int(aggregate["total_bytes"] or 0) * avg_ratio)
        logical_reduction_estimate = max(0, int(aggregate["total_bytes"] or 0) - projected_total_estimate)
    elif exhaustive:
        projected_total_estimate = projected_bytes_scanned
        logical_reduction_estimate = logical_reduction
    return {
        "rows": total_rows,
        "payload_total_bytes": int(aggregate["total_bytes"] or 0),
        "payload_average_bytes": round(float(aggregate["avg_bytes"] or 0), 2),
        "payload_max_bytes": int(aggregate["max_bytes"] or 0),
        "scan_mode": "EXHAUSTIVE_OPERATOR_READ_ONLY" if exhaustive else "BOUNDED_LARGEST_ROW_SAMPLE",
        "rows_scanned": rows_scanned,
        "sample_limit": None if exhaustive else limit,
        "source_bytes_scanned": source_bytes_scanned,
        "projected_bytes_scanned": projected_bytes_scanned,
        "logical_reduction_bytes_scanned": logical_reduction,
        "projected_to_source_ratio": round(ratio, 6) if ratio is not None else None,
        "projection_errors": projection_errors,
        "unchanged_rows": unchanged_rows,
        "projected_total_bytes_estimate": projected_total_estimate,
        "logical_reduction_bytes_estimate": logical_reduction_estimate,
        "estimate_is_exact": bool(exhaustive),
        "row_examples": row_examples,
        "payload_values_exposed": False,
        "historical_rows_mutated": False,
    }


def _archive_foundation_status() -> dict[str, Any]:
    """Report archival foundation availability without creating the sidecar."""
    try:
        from .historical_payload_archive import archive_status
        status = archive_status()
    except Exception as exc:
        status = {"ok": False, "state": "ARCHIVE_STATUS_UNAVAILABLE", "error": f"{type(exc).__name__}: {exc}"}
    return {
        "implemented": True,
        "version": "69.10.11",
        "archive_status": status,
        "production_reads_redirected": False,
        "automatic_historical_archive": False,
        "automatic_historical_rewrite": False,
    }


def audit_historical_payload_compaction(
    *,
    trigger_path: str | Path = TRIGGER_DB,
    evidence_path: str | Path = EVIDENCE_DB,
    exhaustive: bool = False,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> dict[str, Any]:
    """Assess compaction readiness without mutating canonical evidence."""
    tpath, epath = Path(trigger_path), Path(evidence_path)
    trigger: dict[str, Any] = {"path": str(tpath), "exists": tpath.exists()}
    decision: dict[str, Any] = {"path": str(epath), "exists": epath.exists()}
    if tpath.exists():
        try:
            with _read_only(tpath) as c:
                trigger.update(_project_rows(
                    c, table="observed_trade_triggers", id_column="trigger_id", time_column="triggered_at",
                    payload_column="evidence_json", projector=_bounded_trigger_evidence,
                    sample_limit=sample_limit, exhaustive=exhaustive,
                ))
        except Exception as exc:
            trigger["audit_error"] = f"{type(exc).__name__}: {exc}"
    if epath.exists():
        try:
            with _read_only(epath) as c:
                decision.update(_project_rows(
                    c, table="decisions", id_column="decision_id", time_column="observed_at",
                    payload_column="snapshot_json", projector=_persisted_snapshot_projection,
                    sample_limit=sample_limit, exhaustive=exhaustive,
                ))
        except Exception as exc:
            decision["audit_error"] = f"{type(exc).__name__}: {exc}"

    # Readiness is intentionally fail-closed.  Measurable savings do not establish
    # semantic safety while full-payload/fallback consumers remain source-verified.
    blockers = [
        "TRIGGER_HISTORY_FULL_PAYLOAD_CONSUMER_PRESENT",
        "TRIGGER_PREMIUM_EVIDENCE_CONSUMER_PRESENT",
        "DECISION_SNAPSHOT_FALLBACK_CONSUMERS_PRESENT",
        "IMMUTABLE_ARCHIVAL_SIDECAR_NOT_POPULATED_OR_SHADOW_VALIDATED",
    ]
    return {
        "ok": True,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "mode": "READ_ONLY_EXHAUSTIVE" if exhaustive else "READ_ONLY_BOUNDED",
        "trigger_observatory": trigger,
        "evidence_pipeline": decision,
        "dependency_contract": {
            "trigger_evidence": TRIGGER_EVIDENCE_DEPENDENCIES,
            "decision_snapshot": DECISION_SNAPSHOT_DEPENDENCIES,
            "source_verified": True,
            "runtime_verified": False,
        },
        "compaction_readiness": {
            "ready_for_historical_rewrite": False,
            "state": "FOUNDATION_IMPLEMENTED_AWAITING_ARCHIVE_AND_SHADOW_VALIDATION",
            "blockers": blockers,
            "recommended_future_pattern": "IMMUTABLE_ARCHIVAL_SIDECAR_PLUS_CANONICAL_COMPACT_PROJECTION",
            "archive_foundation_version": "69.10.11",
            "production_read_redirect_enabled": False,
            "destructive_in_place_rewrite_recommended": False,
        },
        "archive_foundation": _archive_foundation_status(),
        "guardrails": {
            "read_only": True,
            "historical_rows_mutated": False,
            "canonical_evidence_deleted": False,
            "vacuum_performed": False,
            "filesystem_reclaim_promised": False,
            "payload_values_exposed": False,
            "decision_authority": False,
            "execution_authority": False,
        },
    }
