from engine.institutional_regime_intelligence_v231 import build_regime_intelligence


def test_regime_result_is_read_only_and_complete():
    result = build_regime_intelligence({"ticker":"SPX","trend_day_probability":82,"range_day_probability":18,"dealer_regime":"SHORT_GAMMA","value_migration":"RISING","poc_migration":"RISING"})
    assert result["ok"] is True
    assert result["primary_regime"] in result["scores"]
    assert result["guardrails"]["broker_mutation"] is False
    assert result["guardrails"]["automatic_weight_mutation"] is False


def test_transition_is_defensive_when_history_changes():
    history=[{"regime":"BALANCED_ROTATION"},{"regime":"BALANCED_ROTATION"}]
    result=build_regime_intelligence({"trend_day_probability":90,"range_day_probability":10,"dealer_regime":"SHORT_GAMMA","value_migration":"RISING","poc_migration":"RISING"}, history)
    assert result["transition"]["previous_regime"] == "BALANCED_ROTATION"
    if result["transition"]["changed"]:
        assert result["risk_posture"]["mode"] == "DEFENSIVE"


def test_no_data_never_fabricates_high_confidence():
    result=build_regime_intelligence({})
    assert result["confidence"] <= 70
    assert result["guardrails"]["human_confirmation_required"] is True
