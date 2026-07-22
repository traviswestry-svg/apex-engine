from engine.trade_director_decision_intelligence import build_decision_intelligence


def bullish_context():
    return {
        "session_intelligence":{"session":{"mode":"ATTACK","bias":"BULLISH"},"confidence":80},
        "market_memory":{"predictive_session_planner":{"direction":"BULLISH","confidence":72}},
        "cross_asset_intelligence":{"cross_asset_bias":"BULLISH","confidence":75,"spx_confirmation_score":78},
        "strategy_orchestration":{"decision_gate":"STRATEGY_SELECTED","direction":"BULLISH","confidence":82},
        "options_intelligence":{"decision_gate":"CONTRACT_CANDIDATE_SELECTED","direction":"BULLISH","confidence":80},
        "execution_desk":{"decision_gate":"READY_FOR_PHASE10_PREVIEW","execution_quality_score":75},
        "multi_timeframe_intelligence":{"decision_gate":"ALIGNED","dominant_direction":"BULLISH","confidence":88},
        "flow_intelligence":{"decision_gate":"INSTITUTIONAL_CONFIRMATION","institutional_bias":"BULLISH","confidence":86},
    }


def test_phase19_strong_bullish_consensus():
    d=build_decision_intelligence(bullish_context())
    assert d["decision_state"] in ("BUY","STRONG_BUY")
    assert d["dominant_direction"] == "BULLISH"
    assert d["recommended_action"].endswith("CALL")
    assert d["checklist_passed"] >= 5


def test_phase19_conflict_reduces_conviction():
    c=bullish_context(); c["flow_intelligence"]={"decision_gate":"FLOW_CONFLICT","institutional_bias":"BEARISH","confidence":92}
    d=build_decision_intelligence(c)
    assert d["conflicts"]
    assert d["decision_state"] == "WATCH"


def test_phase19_upstream_stand_down_is_absolute():
    c=bullish_context(); c["strategy_orchestration"]["decision_gate"]="STAND_DOWN"
    d=build_decision_intelligence(c)
    assert d["decision_state"] == "STAND_DOWN"
    assert d["hard_blockers"]


def test_phase19_data_limited_fails_closed():
    d=build_decision_intelligence({"multi_timeframe_intelligence":{"decision_gate":"DATA_LIMITED"}})
    assert d["decision_state"] == "WATCH"
    assert d["evidence_coverage_pct"] < 55
