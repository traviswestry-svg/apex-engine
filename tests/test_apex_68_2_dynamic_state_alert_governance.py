from engine.dynamic_state_policy import evaluate_dynamic_state_policy
from engine.decision_reasoning_contracts import build_engine_opinions, build_correlation_aware_consensus
from engine.trade_director_decision import build_decision_quality


def test_flow_independence_reduces_consensus_weight_without_changing_direction():
    base = {
        "market_state": {"flow_bias": "BULLISH"},
        "flow_intelligence": {"available": True, "bias": "BULLISH", "confidence": 90},
        "institutional_options_flow": {"flow_excitation": {"available": True, "independent_evidence_factor": 0.2}},
        "institutional_intelligence": {"available": True, "bias": "BULLISH", "confidence": 80},
        "auction_intelligence": {"available": True, "bias": "BEARISH", "confidence": 80},
    }
    opinions = build_engine_opinions(base)
    flow = next(o for o in opinions if o["engine_name"] == "flow")
    assert flow["independence_factor"] == 0.2
    consensus = build_correlation_aware_consensus(opinions)
    member = next(x for x in consensus["clusters"]["FLOW_LIQUIDITY"]["members"] if x["engine"] == "flow")
    assert member["independence_factor"] == 0.2


def test_opposing_residual_pressure_penalizes_but_aligned_pressure_does_not_bonus():
    ds = {
        "available": True,
        "flow_excitation": {"available": False},
        "gamma_path": {"available": False},
        "gamma_term_structure": {"available": False},
        "event_phase": {"available": True, "phase": "NORMAL"},
        "residual_pressure": {"available": True, "unresolved": True, "direction": "BEARISH", "remaining_pressure": 60},
    }
    oppose = evaluate_dynamic_state_policy({}, direction="BULLISH", dynamic_state=ds)
    aligned = evaluate_dynamic_state_policy({}, direction="BEARISH", dynamic_state=ds)
    assert oppose["conviction_penalty_points"] > 0
    assert "RESIDUAL_PRESSURE_OPPOSES_DIRECTION" in oppose["warnings"]
    assert aligned["conviction_penalty_points"] == 0


def test_gamma_term_divergence_increases_margin_and_reduces_quality():
    ds = {
        "available": True,
        "flow_excitation": {"available": False},
        "residual_pressure": {"available": False},
        "gamma_path": {"available": False},
        "event_phase": {"available": True, "phase": "NORMAL"},
        "gamma_term_structure": {"available": True, "term_divergence": True, "near_term_fragility": True},
    }
    p = evaluate_dynamic_state_policy({}, direction="BULLISH", dynamic_state=ds)
    assert p["threshold_adjustment_points"] >= 3
    assert p["conviction_penalty_points"] >= 6
    assert p["consensus_penalty_points"] == 3


def test_event_release_suppresses_new_alerts_but_not_position_management():
    snapshot = {
        "direction": "BULLISH", "confidence": 95, "market_open": True, "data_fresh": True,
        "option_liquidity_state": "NORMAL", "execution_score": 90, "position_quality": 90,
        "event_intelligence": {"event_phase": {"available": True, "phase": "RELEASE", "event_key": "FOMC"}},
    }
    fresh = build_decision_quality(snapshot)
    assert fresh["alert_quality"]["alert_eligible"] is False
    assert "EVENT_RELEASE_NEW_ALERT_SUPPRESSION" in fresh["alert_quality"]["blocking_conditions"]

    active = build_decision_quality(snapshot, prior_state={"active": True})
    assert "EVENT_RELEASE_NEW_ALERT_SUPPRESSION" not in active["alert_quality"]["blocking_conditions"]


def test_price_discovery_is_watch_only_for_new_alerts():
    snapshot = {
        "direction": "BULLISH", "confidence": 99, "market_open": True, "data_fresh": True,
        "option_liquidity_state": "NORMAL", "execution_score": 90, "position_quality": 90,
        "event_intelligence": {"event_phase": {"available": True, "phase": "PRICE_DISCOVERY", "event_key": "CPI"}},
    }
    out = build_decision_quality(snapshot)
    assert out["alert_quality"]["state"] == "WATCH_ONLY"
    assert out["dynamic_state_policy"]["watch_only"] is True
    assert out["decision_boundary"]["dynamic_threshold_adjustment"] >= 8
