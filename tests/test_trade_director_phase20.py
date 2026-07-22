from engine.trade_director_institutional_decision_engine import build_institutional_decision_engine


def base():
    return {
        "decision_intelligence":{"decision_state":"STRONG_BUY","recommended_action":"STRONG_BUY_CALL","dominant_direction":"BULLISH","consensus_score":82,"confidence":80,"evidence_coverage_pct":90},
        "session_intelligence":{"session":{"mode":"ATTACK"}},
        "strategy_orchestration":{"decision_gate":"STRATEGY_SELECTED"},
        "options_intelligence":{"decision_gate":"CONTRACT_CANDIDATE_SELECTED","best_contract":{"symbol":"SPXW TEST"}},
        "execution_desk":{"decision_gate":"READY_FOR_PHASE10_PREVIEW","order_plan":{"quantity":1,"limit_price":4.2}},
        "multi_timeframe_intelligence":{"decision_gate":"ALIGNED"},
        "flow_intelligence":{"decision_gate":"INSTITUTIONAL_CONFIRMATION"},
    }

def test_authorized_for_preview():
    d=build_institutional_decision_engine(base())
    assert d["authorization_state"]=="AUTHORIZED_FOR_PREVIEW"
    assert d["authorization"]["broker_execution_enabled"] is False

def test_stand_down_hard_block():
    x=base(); x["decision_intelligence"]["decision_state"]="STAND_DOWN"
    d=build_institutional_decision_engine(x)
    assert d["authorization_state"]=="DECISION_BLOCKED"

def test_missing_contract_waits():
    x=base(); x["options_intelligence"]["decision_gate"]="CHAIN_REQUIRED"
    d=build_institutional_decision_engine(x)
    assert d["authorization_state"] in ("CONDITIONALLY_AUTHORIZED","AWAITING_VALIDATION")

def test_promotion_requires_repeat_when_prior_defensive():
    d=build_institutional_decision_engine(base(), {"authorization_state":"OBSERVE"})
    assert d["authorization_state"]=="AWAITING_VALIDATION"
