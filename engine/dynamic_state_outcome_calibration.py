"""APEX 68.3 — dynamic-state outcome calibration context and summaries."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from .evidence_pipeline import _connect


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _flow_bucket(ief: Any) -> str:
    v = _to_float(ief, 0.0)
    if v <= 0.33:
        return "HIGHLY_REDUNDANT"
    if v <= 0.66:
        return "PARTIALLY_INDEPENDENT"
    return "HIGHLY_INDEPENDENT"


def extract_context(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    dynamic_state = snapshot.get("dynamic_state") if isinstance(snapshot, Mapping) else {}
    dynamic_state = dynamic_state if isinstance(dynamic_state, Mapping) else {}
    decision_quality = snapshot.get("decision_quality") if isinstance(snapshot, Mapping) else {}
    decision_quality = decision_quality if isinstance(decision_quality, Mapping) else {}
    policy = decision_quality.get("dynamic_state_policy") if isinstance(decision_quality, Mapping) else {}
    policy = policy if isinstance(policy, Mapping) else {}
    alert_quality = decision_quality.get("alert_quality") if isinstance(decision_quality, Mapping) else {}
    alert_quality = alert_quality if isinstance(alert_quality, Mapping) else {}
    event_phase = dynamic_state.get("event_phase") if isinstance(dynamic_state, Mapping) else {}
    event_phase = event_phase if isinstance(event_phase, Mapping) else {}
    gamma_term_structure = dynamic_state.get("gamma_term_structure") if isinstance(dynamic_state, Mapping) else {}
    gamma_term_structure = gamma_term_structure if isinstance(gamma_term_structure, Mapping) else {}
    flow_excitation = dynamic_state.get("flow_excitation") if isinstance(dynamic_state, Mapping) else {}
    flow_excitation = flow_excitation if isinstance(flow_excitation, Mapping) else {}
    modifiers = policy.get("modifiers")
    modifiers = modifiers if isinstance(modifiers, list) else []
    residual_opposes = any(
        isinstance(m, Mapping)
        and str(m.get("driver", "")).strip().lower() == "residual_pressure"
        and str(m.get("effect", "")).strip().upper() == "OPPOSES"
        for m in modifiers
    )
    alert_state = str(alert_quality.get("state") or policy.get("state") or "UNKNOWN")
    return {
        "event_phase": str(event_phase.get("phase") or "UNKNOWN"),
        "gamma_term_divergence": _to_bool(gamma_term_structure.get("term_divergence")),
        "gamma_term_fragility": _to_bool(gamma_term_structure.get("near_term_fragility")),
        "residual_pressure_opposes": residual_opposes,
        "flow_independence_bucket": _flow_bucket(flow_excitation.get("independent_evidence_factor")),
        "alert_state": alert_state,
        "threshold_adjustment_points": _to_float(policy.get("threshold_adjustment_points")),
        "conviction_penalty_points": _to_float(policy.get("conviction_penalty_points")),
        "consensus_penalty_points": _to_float(policy.get("consensus_penalty_points")),
    }


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS dynamic_state_decision_context(
          decision_id TEXT PRIMARY KEY,
          context_json TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_dynamic_state_context_created_at ON dynamic_state_decision_context(created_at);
        """
    )


def persist_context(conn: sqlite3.Connection, decision_id: str, snapshot: Mapping[str, Any]) -> bool:
    if not decision_id:
        return False
    ensure_schema(conn)
    payload = json.dumps(extract_context(snapshot), sort_keys=True, separators=(",", ":"))
    conn.execute(
        "INSERT OR IGNORE INTO dynamic_state_decision_context(decision_id,context_json) VALUES(?,?)",
        (decision_id, payload),
    )
    return bool(conn.total_changes)


def calibration_summary(path: str | Path, min_sample: int = 20) -> dict[str, Any]:
    min_sample = max(1, int(min_sample))
    with _connect(path) as conn:
        ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT dc.context_json context_json, gr.outcome_json outcome_json
            FROM dynamic_state_decision_context dc
            JOIN grading_results gr ON gr.decision_id = dc.decision_id
            WHERE gr.status='GRADED'
            """
        ).fetchall()
    dataset: list[dict[str, Any]] = []
    for row in rows:
        try:
            context = json.loads(row["context_json"] or "{}")
        except Exception:
            context = {}
        try:
            outcome = json.loads(row["outcome_json"] or "{}")
        except Exception:
            outcome = {}
        won = _to_bool(outcome.get("won"))
        dataset.append(
            {
                "event_phase": str(context.get("event_phase") or "UNKNOWN"),
                "gamma_term_divergence": str(_to_bool(context.get("gamma_term_divergence"))),
                "gamma_term_fragility": str(_to_bool(context.get("gamma_term_fragility"))),
                "residual_pressure_opposes": str(_to_bool(context.get("residual_pressure_opposes"))),
                "flow_independence_bucket": str(context.get("flow_independence_bucket") or "UNKNOWN"),
                "alert_state": str(context.get("alert_state") or "UNKNOWN"),
                "won": won,
                "directional_move": _to_float(outcome.get("directional_move"), 0.0),
                "mfe": _to_float(outcome.get("mfe"), 0.0),
                "mae": _to_float(outcome.get("mae"), 0.0),
            }
        )

    def summarize(key: str) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in dataset:
            grouped.setdefault(str(item.get(key) or "UNKNOWN"), []).append(item)
        out = []
        for bucket in sorted(grouped):
            samples = grouped[bucket]
            n = len(samples)
            wins = sum(1 for sample in samples if sample["won"])
            out.append(
                {
                    "bucket": bucket,
                    "sample_size": n,
                    "win_rate_pct": round((wins * 100.0 / n), 2) if n else 0.0,
                    "avg_directional_move": round(sum(sample["directional_move"] for sample in samples) / n, 4) if n else 0.0,
                    "avg_mfe": round(sum(sample["mfe"] for sample in samples) / n, 4) if n else 0.0,
                    "avg_mae": round(sum(sample["mae"] for sample in samples) / n, 4) if n else 0.0,
                    "calibration_ready": n >= min_sample,
                }
            )
        return out

    dimensions = {
        "event_phase": summarize("event_phase"),
        "gamma_term_divergence": summarize("gamma_term_divergence"),
        "gamma_term_fragility": summarize("gamma_term_fragility"),
        "residual_pressure_opposes": summarize("residual_pressure_opposes"),
        "flow_independence_bucket": summarize("flow_independence_bucket"),
        "alert_state": summarize("alert_state"),
    }
    all_buckets = [bucket for values in dimensions.values() for bucket in values]
    ready = bool(all_buckets) and all(bucket["calibration_ready"] for bucket in all_buckets)
    return {
        "status": "READY" if ready else "COLLECTING",
        "graded_contexts": len(dataset),
        "minimum_bucket_sample": min_sample,
        "dimensions": dimensions,
        "governance": {
            "advisory_only": True,
            "automatic_threshold_mutation": False,
            "automatic_confidence_mutation": False,
            "automatic_consensus_weight_mutation": False,
        },
    }
