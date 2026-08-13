from engine.trade_director_momentum_lifecycle import build_momentum_lifecycle, compute_entry_quality


def test_entry_quality_fails_closed_without_evidence():
    result = compute_entry_quality({})
    assert result["entry_quality_grade"] == "INSUFFICIENT_DATA"
    assert result["entry_gate"] == "WAIT"


def test_entry_quality_is_separate_precision_score():
    result = compute_entry_quality({
        "level_precision_score": 96, "momentum_score": 94, "liquidity_score": 88,
        "spread_quality_score": 90, "timing_score": 95, "invalidation_clarity_score": 92,
    })
    assert result["entry_quality_grade"] == "A+"
    assert result["entry_gate"] == "ENTRY_ELIGIBLE"


def test_profit_expansion_recommends_take_profit():
    result = build_momentum_lifecycle(position={"status": "OPEN", "option_entry_price": 4.10}, current_premium=6.20)
    assert result["recommendation"] == "TAKE_PROFIT"
    assert result["premium_change"] == 2.10
    assert result["broker_action"] == "NONE"


def test_two_to_three_dollar_adverse_move_exits_now():
    result = build_momentum_lifecycle(position={"status": "OPEN", "option_entry_price": 8.00}, current_premium=5.50, adverse_exit_threshold=2.50)
    assert result["recommendation"] == "EXIT_NOW"
    assert result["lifecycle_state"] == "ENTRY_THESIS_FAILED"


def test_adverse_threshold_is_governed_to_user_range():
    result = build_momentum_lifecycle(position={"status": "OPEN", "option_entry_price": 8.00}, current_premium=6.00, adverse_exit_threshold=9.00)
    assert result["adverse_exit_threshold"] == 3.0
    assert result["recommendation"] == "PROTECT"


def test_missing_fill_premium_cannot_grade_lifecycle():
    result = build_momentum_lifecycle(position={"status": "OPEN"}, current_premium=5.00)
    assert result["recommendation"] == "SYNC_ENTRY"
