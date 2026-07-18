"""APEX 11.3 Decision Review & Replay Intelligence."""
from __future__ import annotations
import datetime as dt
from typing import Any, Dict, List, Mapping, Optional
from . import recommendation_ledger as ledger
from .institutional_decision_object import build_canonical_institutional_decision

VERSION = "11.3.0"
SNAPSHOT_EVENTS = {"STATE_CHANGE", "NARRATIVE_SNAPSHOT", "CONSENSUS_SNAPSHOT", "CONVICTION_SNAPSHOT", "EXECUTION_SNAPSHOT", "POSITION_QUALITY_SNAPSHOT", "RISK_CHANGE", "INVALIDATION_CHANGE", "MARKET_PROGRESS"}


def _d(v: Any) -> Dict[str, Any]: return dict(v) if isinstance(v, Mapping) else {}


def record_decision_snapshot(recommendation_id: str, last_result: Mapping[str, Any], *, event_at: Optional[str] = None) -> Dict[str, Any]:
    obj = build_canonical_institutional_decision(last_result, recommendation_id=recommendation_id)
    created = []
    events = {
        "STATE_CHANGE": {"decision_state": obj["decision_state"], "direction": obj["direction"], "actionable": obj["actionable"]},
        "NARRATIVE_SNAPSHOT": obj["narrative"], "CONSENSUS_SNAPSHOT": obj["consensus"],
        "CONVICTION_SNAPSHOT": obj["conviction"], "EXECUTION_SNAPSHOT": obj["execution_snapshot"],
        "POSITION_QUALITY_SNAPSHOT": obj["position_quality_snapshot"],
        "RISK_CHANGE": {"risks": obj["risks"]}, "INVALIDATION_CHANGE": {"invalidations": obj["invalidations"]},
    }
    existing = ledger.get_recommendation(recommendation_id)
    if existing is None: raise KeyError(recommendation_id)
    previous = {(e["event_type"], str(e.get("payload"))) for e in existing.get("events", [])}
    for event_type, payload in events.items():
        marker = (event_type, str(payload))
        if marker in previous: continue
        ledger.append_event(recommendation_id, event_type, payload, event_at=event_at)
        created.append(event_type)
    return {"ok": True, "recommendation_id": recommendation_id, "events_created": created, "decision": obj}


def build_decision_review(recommendation_id: str) -> Optional[Dict[str, Any]]:
    row = ledger.get_recommendation(recommendation_id)
    if row is None: return None
    snapshots: Dict[str, List[Dict[str, Any]]] = {k.lower(): [] for k in SNAPSHOT_EVENTS}
    lifecycle: List[Dict[str, Any]] = []
    for event in row.get("events", []):
        et = event.get("event_type", "UNKNOWN")
        item = {"event_at": event.get("event_at"), "payload": event.get("payload") or {}}
        if et in SNAPSHOT_EVENTS: snapshots[et.lower()].append(item)
        else: lifecycle.append({"event_type": et, **item})
    explanation = {
        "strategy": row.get("strategy"), "state_at_capture": row.get("state"),
        "confidence": row.get("final_live_confidence"), "evidence": row.get("evidence") or {},
        "probability": row.get("probability") or {}, "confirmation": row.get("confirmation") or {},
        "decision_snapshot": row.get("snapshot") or {},
    }
    outcome = None
    if row.get("outcome_status"):
        outcome = {"status": row.get("outcome_status"), "label": row.get("outcome_label"), "realized_pnl": row.get("realized_pnl"), "realized_r": row.get("realized_r"), "notes": row.get("outcome_notes")}
    return {
        "schema_version": "apex.decision_review.v1", "engine_version": VERSION,
        "recommendation_id": recommendation_id, "captured_at": row.get("captured_at"),
        "explanation": explanation, "evolution_timeline": row.get("events", []),
        "snapshots": snapshots, "lifecycle": lifecycle, "outcome": outcome,
        "outcome_status": "RECORDED" if outcome else "UNRESOLVED",
        "empty_state": None if row.get("events") else "NO_REPLAY_EVENTS_RECORDED",
        "historical_performance_claimed": False,
    }


def build_replay(recommendation_id: str) -> Optional[Dict[str, Any]]:
    review = build_decision_review(recommendation_id)
    if review is None: return None
    frames = []
    for event in review["evolution_timeline"]:
        frames.append({"time": event.get("event_at"), "type": event.get("event_type"), "apex_reasoning": event.get("payload") or {}})
    return {"schema_version": "apex.reasoning_replay.v1", "engine_version": VERSION, "recommendation_id": recommendation_id,
            "status": "AVAILABLE" if frames else "EMPTY", "frames": frames,
            "message": None if frames else "No state-change or market-progression snapshots have been recorded yet."}
