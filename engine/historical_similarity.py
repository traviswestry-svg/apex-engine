"""Leakage-safe historical similarity for APEX 10 Sprint 4.

Similarity is descriptive evidence, never a trade signal. Candidates must be
strictly earlier than the query decision, come from prior sessions by default,
and have labels settled no later than the query time. Outcome data never enters
the distance calculation.
"""
from __future__ import annotations

import math
import statistics
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .feature_store import sample_quality, wilson_interval
from . import feature_store_db

SIMILARITY_VERSION = "10.0.0_HISTORICAL_SIMILARITY"

# Stable, explainable feature policy. Unknown/new fields do not silently affect distance.
CATEGORICAL_WEIGHTS: Dict[str, float] = {
    "event_baseline_bucket": 2.0,
    "intraday_event_regime": 2.0,
    "gamma_regime": 1.6,
    "auction_state": 1.5,
    "cluster_directional_interpretation": 1.8,
    "cluster_option_type": 1.0,
    "cluster_flow_authenticity_state": 1.2,
}
NUMERIC_WEIGHTS: Dict[str, float] = {
    "cluster_aggression_score": 1.4,
    "cluster_repeat_intensity_score": 1.2,
    "cluster_premium_concentration": 1.0,
    "cluster_total_premium": 0.8,
    "cluster_total_contracts": 0.7,
    "cluster_number_of_prints": 0.6,
    "cluster_directional_confidence_adjusted": 1.3,
    "ici": 1.4,
    "vix": 1.0,
    "expected_move": 1.0,
    "distance_to_gamma_flip_pct": 1.1,
    "distance_to_poc_pct": 1.0,
}


def _finite(v: Any) -> Optional[float]:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _robust_scale(values: Sequence[float]) -> float:
    vals = [float(x) for x in values if math.isfinite(float(x))]
    if len(vals) < 2:
        return 1.0
    med = statistics.median(vals)
    mad = statistics.median(abs(x - med) for x in vals)
    if mad > 1e-9:
        return max(1e-9, 1.4826 * mad)
    spread = max(vals) - min(vals)
    return max(1.0, spread / 4.0)


def _distance(query: Mapping[str, Any], candidate: Mapping[str, Any],
              scales: Mapping[str, float]) -> Dict[str, Any]:
    weighted = 0.0
    used = 0.0
    factors: List[Dict[str, Any]] = []

    for key, weight in CATEGORICAL_WEIGHTS.items():
        q, c = query.get(key), candidate.get(key)
        if q is None or c is None:
            continue
        match = str(q) == str(c)
        d = 0.0 if match else 1.0
        weighted += weight * d
        used += weight
        factors.append({"feature": key, "kind": "categorical", "query": q,
                        "candidate": c, "distance": d, "weight": weight,
                        "match": match})

    for key, weight in NUMERIC_WEIGHTS.items():
        q, c = _finite(query.get(key)), _finite(candidate.get(key))
        if q is None or c is None:
            continue
        scale = max(1e-9, float(scales.get(key) or 1.0))
        raw = abs(q - c) / scale
        d = min(1.0, raw / 3.0)  # cap a 3-scale difference at maximum distance
        weighted += weight * d
        used += weight
        factors.append({"feature": key, "kind": "numeric", "query": q,
                        "candidate": c, "scale": round(scale, 6),
                        "distance": round(d, 6), "weight": weight})

    if used <= 0:
        return {"score": 0.0, "coverage_weight": 0.0, "factors": []}
    score = max(0.0, 100.0 * (1.0 - weighted / used))
    return {"score": round(score, 2), "coverage_weight": round(used, 3),
            "factors": sorted(factors, key=lambda x: x["weight"] * x["distance"], reverse=True)}


def _outcome_summary(matches: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    labelled = [m for m in matches if m.get("labels")]
    n = len(labelled)
    quality = sample_quality(n)
    counts: Dict[str, int] = {}
    for m in labelled:
        outcome = (m.get("labels") or {}).get("final_outcome")
        if outcome:
            counts[outcome] = counts.get(outcome, 0) + 1
    successes = counts.get("TARGET_FIRST", 0) + counts.get("TARGET_ONLY", 0)
    summary: Dict[str, Any] = {
        "labelled_match_count": n,
        "outcome_counts": counts,
        "evidence_tier": quality["tier"],
        "edge_claim_permitted": quality["edge_claim_permitted"],
        "note": quality["note"],
        "target_first_interval": None,
    }
    if quality["edge_claim_permitted"] and n:
        summary["target_first_interval"] = wilson_interval(successes, n)
    else:
        summary["rate_withheld_because"] = quality["note"]
    return summary


def find_similar(*, query_features: Mapping[str, Any], decision_time: str,
                 ticker: str = "SPX", top_k: int = 10,
                 min_score: float = 55.0, prior_sessions_only: bool = True,
                 exclude_sample_id: Optional[str] = None) -> Dict[str, Any]:
    """Return prior, fully settled neighbours without using outcomes in distance."""
    candidates = feature_store_db.load_similarity_candidates(
        decision_time=decision_time, ticker=ticker,
        prior_sessions_only=prior_sessions_only,
        exclude_sample_id=exclude_sample_id,
    )
    scales: Dict[str, float] = {}
    for key in NUMERIC_WEIGHTS:
        vals = [_finite((c.get("features") or {}).get(key)) for c in candidates]
        scales[key] = _robust_scale([v for v in vals if v is not None])

    matches: List[Dict[str, Any]] = []
    for c in candidates:
        dist = _distance(query_features, c.get("features") or {}, scales)
        if dist["score"] < float(min_score) or dist["coverage_weight"] <= 0:
            continue
        matches.append({
            "sample_id": c["sample_id"],
            "session_date": c["session_date"],
            "decision_time": c["decision_time"],
            "similarity_score": dist["score"],
            "comparable_weight": dist["coverage_weight"],
            "top_differences": dist["factors"][:5],
            "labels": c.get("labels"),
            "settled_at": c.get("settled_at"),
        })
    matches.sort(key=lambda x: (-x["similarity_score"], x["decision_time"]))
    matches = matches[:max(1, min(int(top_k or 10), 50))]
    return {
        "version": SIMILARITY_VERSION,
        "decision_time": decision_time,
        "ticker": ticker,
        "candidate_count": len(candidates),
        "matched_count": len(matches),
        "matches": matches,
        "outcome_evidence": _outcome_summary(matches),
        "guardrails": {
            "outcomes_used_in_distance": False,
            "strictly_prior_decisions_only": True,
            "labels_must_be_settled_by_query_time": True,
            "prior_sessions_only": bool(prior_sessions_only),
            "similarity_is_trade_signal": False,
        },
    }


def find_similar_to_sample(sample_id: str, *, top_k: int = 10,
                           min_score: float = 55.0) -> Dict[str, Any]:
    query = feature_store_db.get_features(sample_id)
    if not query:
        return {"version": SIMILARITY_VERSION, "sample_id": sample_id,
                "available": False, "reason": "sample not found", "matches": []}
    out = find_similar(query_features=query["features"],
                       decision_time=query["decision_time"],
                       ticker=query.get("ticker") or "SPX", top_k=top_k,
                       min_score=min_score, exclude_sample_id=sample_id)
    out.update({"sample_id": sample_id, "available": True})
    return out
