import datetime as dt
from engine import institutional_decision_integrity_v250 as engine


def fresh_payload():
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    return {
        "generated_at": now,
        "confidence": 82,
        "direction": "CALLS",
        "market_state": {"price": 6300, "generated_at": now},
        "institutional_intelligence": {
            "institutional_bias": "BULLISH", "ici_score": 82,
            "evidence": ["Price above VWAP", "Bullish institutional flow"],
            "invalidation": ["Lose VWAP"], "generated_at": now,
        },
        "flow_intelligence": {"bias": "BULLISH", "generated_at": now},
        "dealer_positioning": {"gamma_regime": "NEGATIVE", "generated_at": now},
        "multi_timeframe": {"dominant_bias": "BULLISH", "generated_at": now},
        "market_memory": {"matches": 12, "generated_at": now},
        "historical_similarity": {"matches": 8, "generated_at": now},
        "confidence_calibration": {"status": "READY", "generated_at": now},
    }


def test_healthy_evidence_is_eligible():
    result = engine.evaluate_decision(fresh_payload())
    assert result["decision"]["execution_eligibility"] == "ELIGIBLE"
    assert result["decision"]["integrity_adjusted_confidence"] == 82
    assert result["evidence_health"]["state"] == "HEALTHY"
    assert result["guardrails"]["automatic_order_submission"] is False


def test_missing_market_state_forces_stand_down():
    payload = fresh_payload()
    payload.pop("market_state")
    result = engine.evaluate_decision(payload)
    assert result["decision"]["execution_eligibility"] == "STAND_DOWN"
    assert result["decision"]["confidence_ceiling"] == 0
    assert "market_state" in result["evidence_health"]["critical_degraded"]


def test_unavailable_evidence_is_not_neutral():
    payload = fresh_payload()
    payload["flow_intelligence"] = {"status": "ERROR", "error": "provider timeout"}
    health = engine.evaluate_evidence_health(payload)
    flow = next(x for x in health["sources"] if x["source"] == "flow")
    assert flow["state"] == "FAILED"
    assert flow["neutral_interpretation_allowed"] is False


def test_stale_critical_evidence_caps_confidence():
    payload = fresh_payload()
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=10)).isoformat()
    payload["institutional_intelligence"]["generated_at"] = old
    result = engine.evaluate_decision(payload)
    assert result["decision"]["confidence_ceiling"] <= 40
    assert result["decision"]["execution_eligibility"] == "STAND_DOWN"


def test_status_is_advisory_only():
    status = engine.status()
    assert status["version"].startswith("25.0.0")
    assert status["production_effect"] == "NONE"
