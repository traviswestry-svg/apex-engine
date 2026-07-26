from engine.liquidity_race import evaluate


def test_equal_orders_use_directional_evidence():
    result = evaluate({
        "current_price": 7000, "upper_level": 7030, "lower_level": 6980,
        "upper_size": 1000, "lower_size": 1000,
        "order_flow_score": 78, "delta_score": 72, "momentum_score": 70,
        "structure_score": 65, "auction_score": 60,
    })
    assert result["ok"] is True
    assert result["leader"] == "UPPER"
    assert result["upper"]["probability_first_pct"] > 50


def test_closer_lower_level_has_only_small_proximity_edge():
    result = evaluate({
        "current_price": 7000, "upper_level": 7030, "lower_level": 6990,
        "upper_size": 1000, "lower_size": 1000,
        "order_flow_score": 50, "delta_score": 50, "momentum_score": 50,
        "structure_score": 50, "auction_score": 50,
    })
    assert result["leader"] == "BALANCED"
    assert result["lower"]["probability_first_pct"] < 70


def test_invalid_levels_fail_closed():
    result = evaluate({"current_price": 7000, "upper_level": 6990, "lower_level": 6980})
    assert result["ok"] is False
    assert result["status"] == "INSUFFICIENT_LEVELS"
