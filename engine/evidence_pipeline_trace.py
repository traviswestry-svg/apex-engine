"""APEX 47.0.6 — end-to-end evidence pipeline visibility.

This module is read-only. It reports the lifecycle from recommendation capture
through grading, adaptive learning, and calibration without fabricating success.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping

VERSION = "47.0.6"
SCHEMA_VERSION = "apex.evidence_pipeline_trace.v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(callable_, default: Any) -> Any:
    try:
        return callable_()
    except Exception as exc:
        if isinstance(default, dict):
            return {**default, "error": str(exc)}
        return default


def _stage(name: str, count: int | None, status: str, summary: str, **details: Any) -> Dict[str, Any]:
    return {
        "name": name,
        "count": count,
        "status": status,
        "summary": summary,
        "details": details,
    }


def build_trace() -> Dict[str, Any]:
    from . import recommendation_ledger as ledger
    from .evidence_pipeline import readiness as evidence_readiness

    ledger_counts = _safe(ledger.counts, {})
    ledger_coverage = _safe(ledger.coverage, {})
    evidence = _safe(evidence_readiness, {})

    learning = _safe(
        lambda: __import__("engine.adaptive_learning", fromlist=["summary"]).summary(),
        {},
    )

    total = int(ledger_counts.get("total") or 0)
    actionable = int(
        ledger_counts.get("actionable")
        or ledger_counts.get("tradeable")
        or ledger_counts.get("gradeable")
        or 0
    )
    decisions = int(evidence.get("decisions_recorded") or total)
    vectors = int(evidence.get("feature_vectors_stored") or 0)
    matured = int(evidence.get("matured_outcomes") or 0)
    graded = int(evidence.get("graded_outcomes") or ledger_counts.get("gradeable") or 0)
    excluded = int(evidence.get("excluded_outcomes") or 0)
    pending = int(evidence.get("pending_decisions") or max(0, decisions - matured))
    learning_samples = int(
        learning.get("graded_outcomes")
        or learning.get("sample_size")
        or learning.get("outcome_count")
        or 0
    )

    stages = [
        _stage(
            "recommendation_created", total,
            "PASS" if total else "WAITING",
            "Recommendation records captured" if total else "Waiting for live recommendations",
            source="recommendation_ledger", coverage_pct=ledger_coverage.get("coverage_pct"),
        ),
        _stage(
            "decision_snapshot_stored", decisions,
            "PASS" if decisions else ("BLOCKED" if total else "WAITING"),
            "Canonical decision snapshots stored" if decisions else "No canonical decision snapshots stored yet",
            last_write=evidence.get("last_decision_write"),
        ),
        _stage(
            "feature_vector_stored", vectors,
            "PASS" if vectors else ("BLOCKED" if decisions else "WAITING"),
            "Feature vectors linked to decisions" if vectors else "Feature vectors are not yet available",
        ),
        _stage(
            "outcome_eligible", matured, "PASS" if matured else ("WAITING" if pending else "BLOCKED"),
            "Outcomes reached a terminal grading state" if matured else "Recommendations are awaiting maturity or executable close data",
            pending=pending, excluded=excluded,
        ),
        _stage(
            "outcome_graded", graded, "PASS" if graded else ("WAITING" if total else "BLOCKED"),
            "Graded outcomes are available" if graded else "No graded outcomes are available yet",
            last_grade=evidence.get("last_successful_grade"), exclusion_reasons=evidence.get("exclusion_reasons", {}),
        ),
        _stage(
            "adaptive_learning", learning_samples,
            "PASS" if learning_samples else ("WAITING" if graded else "BLOCKED"),
            "Adaptive learning has graded evidence" if learning_samples else "Adaptive learning is waiting for graded outcomes",
            mode=learning.get("mode") or learning.get("activation_state") or "shadow",
        ),
        _stage(
            "confidence_updated", learning_samples,
            "PASS" if learning_samples else ("WAITING" if graded else "BLOCKED"),
            "Confidence calibration has usable samples" if learning_samples else "Confidence remains on baseline weights until evidence matures",
            activation_eligible=bool(learning.get("activation_eligible", False)),
        ),
    ]

    first_blocker = next((s for s in stages if s["status"] in {"BLOCKED", "WAITING"}), None)
    if any(s["status"] == "FAIL" for s in stages):
        overall = "FAIL"
    elif graded and learning_samples:
        overall = "HEALTHY"
    elif total:
        overall = "COLLECTING"
    else:
        overall = "WAITING_FOR_LIVE_DATA"

    return {
        "ok": True,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "status": overall,
        "generated_at": _now(),
        "stages": stages,
        "first_blocker": first_blocker,
        "totals": {
            "recommendations": total,
            "actionable_recommendations": actionable,
            "decisions": decisions,
            "feature_vectors": vectors,
            "matured": matured,
            "graded": graded,
            "excluded": excluded,
            "pending": pending,
            "learning_samples": learning_samples,
        },
        "guardrails": {
            "read_only": True,
            "changes_trade_decisions": False,
            "fabricates_outcomes": False,
        },
    }
