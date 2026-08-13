from engine.trade_director_multi_timeframe import build_multi_timeframe_intelligence


def frame(direction, strength=80):
    return {"direction": direction, "strength": strength}


def test_phase17_aligned_bullish_stack():
    data = {"1D": frame("bullish", 85), "4H": frame("bullish", 82), "1H": frame("bullish", 78), "15M": frame("bullish", 74), "5M": frame("bullish", 72), "1M": frame("neutral", 55)}
    result = build_multi_timeframe_intelligence({}, data)
    assert result["decision_gate"] == "ALIGNED"
    assert result["dominant_direction"] == "BULLISH"
    assert result["entry_timing"] == "ENTRY_WINDOW_OPEN"


def test_phase17_detects_higher_lower_conflict():
    data = {"1D": frame("bearish"), "4H": frame("bearish"), "1H": frame("bearish"), "15M": frame("bullish"), "5M": frame("bullish"), "1M": frame("bullish")}
    result = build_multi_timeframe_intelligence({}, data)
    assert result["decision_gate"] == "TIMEFRAME_CONFLICT"
    assert result["entry_timing"] == "AVOID_ENTRY"
    assert result["conflicts"]


def test_phase17_fails_closed_with_insufficient_coverage():
    result = build_multi_timeframe_intelligence({}, {"5M": frame("bullish"), "1M": frame("bullish")})
    assert result["decision_gate"] == "DATA_LIMITED"
    assert result["trade_director_effect"]["sizing_posture"] == "REDUCED"


def test_phase17_preserves_stand_down_authority():
    context = {"strategy_orchestration": {"decision_gate": "STAND_DOWN"}}
    data = {"1D": frame("bullish"), "1H": frame("bullish"), "5M": frame("bullish")}
    result = build_multi_timeframe_intelligence(context, data)
    assert result["decision_gate"] == "STAND_DOWN"
    assert result["trade_director_effect"]["sizing_posture"] == "ZERO"
