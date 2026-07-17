from engine.institutional_state import build_institutional_state


def sample_result():
    return {
        "ticker": "SPX",
        "decision_state": "WATCH_CALLS",
        "confidence": 78,
        "market_state": {
            "auction_state": "ACCEPTANCE_HIGHER",
            "poc_migration": "RISING",
            "flow_bias": "BULLISH",
            "chain_quality": {"quality_score": 92},
            "chain_quality_gate": {"action": "ALLOW", "multiplier": .92},
        },
        "chain_quality": {"quality_score": 92},
        "chain_quality_gate": {"action": "ALLOW", "multiplier": .92},
        "intraday_event_regime": {"state": "NORMAL_SESSION"},
        "confidence_attribution": {"effective_confidence": 74, "calibrated_confidence": 71},
        "institutional_intelligence": {
            "institutional_bias": "BULLISH",
            "decision_state": "WATCH_CALLS",
            "decision_recommendation": "WATCH — bullish evidence developing.",
            "auction_bias": "ACCEPTANCE_HIGHER",
            "flow_bias": "BULLISH",
            "flow_conviction": 81,
            "flow_urgency": "HIGH",
            "gamma_regime": "NEGATIVE_GAMMA",
            "delta_bias": "BUYING",
            "vol_regime": "NORMAL",
            "vol_path": "STABLE",
            "highest_probability_scenario": "Continuation if value migrates higher.",
            "primary_risk": "Loss of value acceptance.",
            "session_state": "MARKET_OPEN",
        },
        "flow_intelligence_2": {"flow_bias": "BULLISH", "flow_conviction": 81},
        "dealer_positioning": {"gamma": {"regime": "NEGATIVE_GAMMA"}, "delta": {"bias": "BUYING"}},
        "volatility": {"regime": "NORMAL"},
        "execution_intelligence": {"liquidity_state": "HEALTHY"},
    }


def test_builds_canonical_state_and_graph_without_recomputing_direction():
    out = build_institutional_state(current_result=sample_result(), ticker="SPX")
    assert out["available"] is True
    assert out["market_state"]["bias"] == "BULLISH"
    assert out["market_state"]["decision_state"] == "WATCH_CALLS"
    assert out["market_state"]["confidence"] == 71
    ids = {n["id"] for n in out["evidence_graph"]["nodes"]}
    assert {"auction", "flow", "dealer", "quality", "confidence"}.issubset(ids)
    assert out["guardrails"]["recomputes_direction"] is False
    assert out["guardrails"]["fabricates_institutional_intent"] is False


def test_state_hash_is_deterministic_for_same_decision_inputs():
    one = build_institutional_state(current_result=sample_result(), ticker="SPX")
    two = build_institutional_state(current_result=sample_result(), ticker="SPX")
    assert one["state_hash"] == two["state_hash"]
    changed = sample_result()
    changed["institutional_intelligence"]["flow_conviction"] = 60
    three = build_institutional_state(current_result=changed, ticker="SPX")
    assert one["state_hash"] != three["state_hash"]


def test_story_is_structured_and_trace_is_explicit():
    out = build_institutional_state(current_result=sample_result())
    story = out["market_story"]
    assert story["headline"] == "Bullish institutional state"
    assert "Auction:" in story["narrative"]
    assert "not generated market intent" in story["guardrail"]
    assert [x["name"] for x in out["decision_trace"]] == [
        "INGEST", "QUALITY_GATE", "SYNTHESIZE", "CONFLICT_CHECK", "DECISION"
    ]


def test_empty_result_is_honest():
    out = build_institutional_state(current_result={}, ticker="SPX")
    assert out["available"] is False
    assert out["market_state"]["decision_state"] == "NO_TRADE"
    assert out["market_story"]["decision_recommendation"] == "NO TRADE"
