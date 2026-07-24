from engine.trade_director_decision_quality import build_decision_quality, build_flow_participation


def _flow(size=200, premium=100000, strike=7500, delta=.5, kind="BLOCK", effect="OPENING"):
    return {"size": size, "premium": premium, "strike": strike, "delta": delta,
            "trade_type": kind, "position_effect": effect}


def test_flow_participation_uses_premium_delta_size_and_concentration():
    result = build_flow_participation({"flow": [_flow(), _flow(size=5, premium=10000, strike=7510)]})
    assert result["status"] == "READY"
    assert result["delta_adjusted_notional"] == 55000.0
    assert result["block_share_pct"] > result["small_lot_share_pct"]
    assert result["strike_concentration_pct"] == 100.0


def test_decision_quality_fails_closed_on_stale_data():
    result = build_decision_quality({"direction": "BULLISH", "confidence": 95, "data_fresh": False})
    assert result["alert_quality"]["alert_eligible"] is False
    assert "STALE_OR_MISSING_DATA" in result["alert_quality"]["blocking_conditions"]


def test_decision_boundary_requires_margin_not_threshold_touch():
    result = build_decision_quality({"direction": "BULLISH", "confidence": 81, "market_open": True,
                                     "data_fresh": True, "liquidity_state": "NORMAL",
                                     "flow": [_flow()]})
    assert result["decision_boundary"]["margin_points"] == 1.0
    assert result["alert_quality"]["state"] == "WATCH_ONLY"
    assert "INSUFFICIENT_BOUNDARY_MARGIN" in result["alert_quality"]["blocking_conditions"]


def test_hysteresis_uses_lower_exit_boundary_for_active_state():
    result = build_decision_quality({"direction": "BULLISH", "confidence": 75, "position_active": True,
                                     "market_open": True, "data_fresh": True, "liquidity_state": "NORMAL",
                                     "flow": [_flow()]})
    assert result["decision_boundary"]["applied_threshold"] == 72.0
    assert result["decision_boundary"]["active_state"] is True


def test_small_lot_dominated_flow_suppresses_alert():
    flows = [_flow(size=2, premium=10000, strike=7500 + i, kind="TRADE") for i in range(6)]
    result = build_decision_quality({"direction": "BULLISH", "confidence": 95, "market_open": True,
                                     "data_fresh": True, "liquidity_state": "NORMAL", "flow": flows})
    assert "SMALL_LOT_DOMINATED_FLOW" in result["alert_quality"]["blocking_conditions"]


def test_policy_metrics_collecting_is_honest():
    result = build_decision_quality({"direction": "NEUTRAL", "confidence": 0})
    assert result["policy_quality"]["status"] == "COLLECTING"
    assert result["governance"]["next_executable_price_required_for_grading"] is True
