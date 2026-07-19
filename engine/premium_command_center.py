"""APEX 18.0.8 — Premium Discipline Command Center read model.

Builds a bounded, read-only operational view over premium eligibility,
refusal replay, and governed calibration. No execution authority is exposed.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

VERSION = "18.0.8_PREMIUM_DISCIPLINE_COMMAND_CENTER"


def _loads(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def serialize_decision(row: Dict[str, Any]) -> Dict[str, Any]:
    """Return the UI-safe, explainable subset of a ledger row."""
    decision = _loads(row.get("decision_json"), {})
    candidate = _loads(row.get("candidate_json"), {})
    metrics = _loads(row.get("counterfactual_metrics_json"), {})
    return {
        "id": row.get("id"),
        "ts": row.get("ts"),
        "session_date": row.get("session_date"),
        "ticker": row.get("ticker"),
        "strategy": row.get("strategy"),
        "decision": row.get("decision"),
        "eligibility_score": row.get("eligibility_score"),
        "threshold": row.get("threshold"),
        "blockers": _loads(row.get("blockers_json"), []),
        "warnings": _loads(row.get("warnings_json"), []),
        "headline": decision.get("headline"),
        "factors": decision.get("factors") or [],
        "candidate": {
            "strategy": candidate.get("strategy"),
            "tradeable": candidate.get("tradeable"),
            "credit": candidate.get("credit") or candidate.get("net_credit"),
            "short_put": candidate.get("short_put"),
            "long_put": candidate.get("long_put"),
            "short_call": candidate.get("short_call"),
            "long_call": candidate.get("long_call"),
        },
        "counterfactual_outcome": row.get("counterfactual_outcome"),
        "counterfactual_pnl": row.get("counterfactual_pnl"),
        "counterfactual_notes": row.get("counterfactual_notes"),
        "counterfactual_metrics": metrics,
        "graded_at": row.get("graded_at"),
        "replay_version": row.get("replay_version"),
    }


def build_command_center(*, snapshot: Dict[str, Any], decisions: List[Dict[str, Any]],
                         scorecard: Dict[str, Any], replay: Dict[str, Any],
                         active_policy: Dict[str, Any], calibration_runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    latest_run = calibration_runs[0] if calibration_runs else None
    recommendation = (latest_run or {}).get("recommendation") or {}
    readiness = "NO_HISTORY"
    if latest_run:
        readiness = "READY_TO_PROMOTE" if recommendation.get("status") == "RECOMMENDED" and not latest_run.get("promoted_at") else (
            "PROMOTED" if latest_run.get("promoted_at") else recommendation.get("status", "UNKNOWN")
        )
    return {
        "version": VERSION,
        "advisory_only": True,
        "execution_authority": False,
        "current": snapshot,
        "scorecard": scorecard,
        "replay": replay,
        "active_policy": active_policy,
        "latest_calibration": latest_run,
        "calibration_readiness": readiness,
        "decisions": [serialize_decision(row) for row in decisions],
        "audit": {
            "decision_rows": len(decisions),
            "calibration_runs": len(calibration_runs),
            "active_policy_source": active_policy.get("source"),
            "active_source_run_id": active_policy.get("source_run_id"),
        },
    }
