from engine.trade_director_flow_intelligence import build_flow_intelligence


def event(side="call", aggressor="ask", premium=250000, kind="sweep", opening="opening", strike=6000):
    return {"option_type": side, "aggressor": aggressor, "premium": premium, "size": 200, "trade_type": kind, "position_effect": opening, "strike": strike, "expiration": "2026-07-22"}


def test_phase18_confirms_bullish_institutional_flow():
    flow = [event(), event(premium=180000, kind="block", strike=6010), event(premium=120000, kind="split", strike=6020)]
    result = build_flow_intelligence({"multi_timeframe_intelligence": {"dominant_direction": "BULLISH"}, "gamma": {"regime": "SHORT_GAMMA"}}, flow)
    assert result["decision_gate"] == "INSTITUTIONAL_CONFIRMATION"
    assert result["institutional_bias"] == "BULLISH"
    assert result["dealer_hedging"]["flow_effect"] == "AMPLIFY"


def test_phase18_detects_flow_conflict():
    flow = [event(), event(premium=180000), event(premium=140000)]
    result = build_flow_intelligence({"multi_timeframe_intelligence": {"dominant_direction": "BEARISH"}}, flow)
    assert result["decision_gate"] == "FLOW_CONFLICT"
    assert result["conflicts"]
    assert result["trade_director_effect"]["sizing_posture"] == "ZERO"


def test_phase18_fails_closed_without_enough_flow():
    result = build_flow_intelligence({}, [event(premium=10000)])
    assert result["decision_gate"] == "DATA_LIMITED"
    assert result["trade_director_effect"]["sizing_posture"] == "REDUCED"


def test_phase18_preserves_stand_down_authority():
    flow = [event(), event(), event()]
    result = build_flow_intelligence({"strategy_orchestration": {"decision_gate": "STAND_DOWN"}}, flow)
    assert result["decision_gate"] == "STAND_DOWN"
    assert result["trade_director_effect"]["sizing_posture"] == "ZERO"


def test_phase18_interprets_puts_sold_at_bid_as_bullish():
    flow = [event(side="put", aggressor="bid", premium=200000), event(side="put", aggressor="bid", premium=180000), event(side="put", aggressor="bid", premium=160000)]
    result = build_flow_intelligence({}, flow)
    assert result["institutional_bias"] == "BULLISH"
