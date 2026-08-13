"""APEX 10 Sprint 6 — dashboard composition for evidence and trust.

This module is deliberately read-only.  It does not recompute directional logic,
activate learning policies, or turn historical similarity into a trade signal.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from . import feature_store_db
from .historical_similarity import find_similar_to_sample
from .learning_calibration import active_policy, calibration_report

VERSION = "1.0.0"


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _latest_sample(ticker: str) -> Optional[Dict[str, Any]]:
    rows = feature_store_db.list_features(limit=25)
    ticker = str(ticker or "SPX").upper()
    return next((row for row in rows if str(row.get("ticker") or "").upper() == ticker), None)


def build_dashboard_evidence(*, current_result: Optional[Dict[str, Any]] = None,
                             ticker: str = "SPX") -> Dict[str, Any]:
    """Compose UI-ready evidence without changing any engine output."""
    current = _dict(current_result)
    market_state = _dict(current.get("market_state"))
    quality = (_dict(current.get("chain_quality")) or
               _dict(current.get("chain_quality_gate")) or
               _dict(market_state.get("chain_quality")))
    quality_gate = (_dict(current.get("chain_quality_gate")) or
                    _dict(market_state.get("chain_quality_gate")))
    event = (_dict(current.get("intraday_event_regime")) or
             _dict(_dict(current.get("event_intelligence")).get("intraday_event_regime")))
    attribution = _dict(current.get("confidence_attribution"))

    sample = _latest_sample(ticker) if feature_store_db.is_ready() else None
    similarity: Dict[str, Any] = {
        "available": False,
        "reason": "No frozen feature sample is available for this ticker.",
        "matches": [],
    }
    if sample:
        similarity = find_similar_to_sample(str(sample.get("sample_id")))

    sessions = feature_store_db.sessions("features") if feature_store_db.is_ready() else []
    calibration: Dict[str, Any] = {
        "available": False,
        "reason": "At least two settled sessions are required.",
        "active_policy": active_policy(),
    }
    if len(sessions) >= 2:
        cut = max(1, int(len(sessions) * 0.8))
        if cut >= len(sessions):
            cut = len(sessions) - 1
        pairs = feature_store_db.load_training_pairs(
            train_sessions=sessions[:cut], eval_sessions=sessions[cut:]
        )
        calibration = {
            "available": True,
            "train": calibration_report(pairs.get("train") or []),
            "evaluation": calibration_report(pairs.get("eval") or []),
            "active_policy": active_policy(),
        }

    return {
        "available": bool(current or sample),
        "version": VERSION,
        "ticker": str(ticker or "SPX").upper(),
        "quality": quality,
        "quality_gate": quality_gate,
        "event_regime": event,
        "confidence_attribution": attribution,
        "latest_sample": {
            "sample_id": sample.get("sample_id"),
            "decision_time": sample.get("decision_time"),
            "session_date": sample.get("session_date"),
            "feature_count": sample.get("feature_count"),
            "schema_version": sample.get("schema_version"),
        } if sample else None,
        "similarity": similarity,
        "calibration": calibration,
        "guardrails": {
            "read_only": True,
            "similarity_is_trade_signal": False,
            "learning_auto_activation": False,
            "dashboard_recomputes_direction": False,
        },
    }
