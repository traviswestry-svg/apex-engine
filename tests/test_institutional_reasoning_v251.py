from datetime import datetime, timezone
from engine import institutional_reasoning_v251 as reasoning


def payload():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "direction": "CALL",
        "confidence": 88,
        "as_of": now,
        "market_state": {"as_of": now, "bias": "bullish", "status": "ACTIVE"},
        "institutional_intelligence": {"as_of": now, "institutional_bias": "bullish", "confidence": 91, "evidence": ["buyers defended value", "acceptance above VWAP"]},
        "flow": {"as_of": now, "bias": "bullish", "confidence": 80},
        "dealer_positioning": {"as_of": now, "bias": "bullish", "confidence": 76},
        "multi_timeframe": {"as_of": now, "dominant_bias": "bullish", "alignment_score": 83},
        "market_memory": {"as_of": now, "status": "READY"},
        "historical_similarity": {"as_of": now, "best_match": {"date": "2026-04-18", "similarity": .91, "average_move_points": 34}},
        "confidence_calibration": {"as_of": now, "status": "READY"},
        "story_timeline": [{"time": "09:30", "event": "Opening drive"}, {"time": "09:48", "event": "Acceptance above value"}],
    }


def test_build_reasoning_returns_ranked_evidence_and_waterfall():
    result = reasoning.build_reasoning(payload())
    assert result["ok"] is True
    assert result["reasoning"]["evidence_rankings"]
    assert result["reasoning"]["confidence_waterfall"][0]["kind"] == "BASE"
    assert result["reasoning"]["historical_match"]["similarity_pct"] == 91
    assert result["guardrails"]["automatic_order_submission"] is False


def test_failed_evidence_is_not_ranked_as_supportive_weight():
    data = payload()
    data["flow"] = {"as_of": data["as_of"], "status": "FAILED", "error": "provider unavailable"}
    ranked = reasoning.rank_evidence(data)
    flow = next(item for item in ranked if item["source"] == "flow")
    assert flow["health"] == "FAILED"
    assert flow["importance_score"] == 0


def test_reasoning_is_deterministic_for_same_payload_except_timestamp():
    first = reasoning.build_reasoning(payload())["reasoning"]
    second = reasoning.build_reasoning(payload())["reasoning"]
    assert first == second
