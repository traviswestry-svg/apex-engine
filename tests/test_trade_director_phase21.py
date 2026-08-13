from engine.trade_director_trade_lifecycle import build_trade_lifecycle


def base_context():
    return {
        "session_intelligence": {"session": {"mode": "ATTACK"}},
        "strategy_orchestration": {"decision_gate": "STRATEGY_SELECTED", "selected_strategy": "LONG_CALL"},
        "options_intelligence": {"decision_gate": "CONTRACT_CANDIDATE_SELECTED", "best_contract": {"symbol": "SPXW TEST"}},
        "execution_desk": {"decision_gate": "READY_FOR_PHASE10_PREVIEW"},
        "multi_timeframe_intelligence": {"decision_gate": "ALIGNED", "dominant_direction": "BULLISH"},
        "flow_intelligence": {"decision_gate": "INSTITUTIONAL_CONFIRMATION", "institutional_bias": "BULLISH"},
        "decision_intelligence": {"dominant_direction": "BULLISH"},
        "institutional_decision_engine": {
            "decision_id": "D20-TEST",
            "authorization_state": "AUTHORIZED_FOR_PREVIEW",
            "dominant_direction": "BULLISH",
        },
    }


def test_authorized_without_position_routes_to_phase10_preview():
    data = build_trade_lifecycle(base_context())
    assert data["lifecycle_state"] == "ENTRY_PENDING"
    assert data["management_action"] == "PROCEED_TO_PHASE10_PREVIEW"
    assert data["management_plan"]["requires_phase10_exact_confirmation"] is True
    assert data["management_plan"]["broker_called"] is False


def test_active_position_holds_when_integrated_thesis_is_intact():
    context = base_context()
    context["position"] = {
        "status": "OPEN", "quantity": 2, "entry_price": 10.0, "current_price": 10.8,
        "trade_health_score": 82, "momentum_state": "STRONG",
    }
    data = build_trade_lifecycle(context)
    assert data["lifecycle_state"] == "POSITION_ACTIVE"
    assert data["management_action"] == "HOLD_POSITION"
    assert data["thesis"]["intact"] is True


def test_tp1_scales_and_moves_protection_to_breakeven():
    context = base_context()
    context["position"] = {
        "status": "OPEN", "quantity": 3, "entry_price": 10.0, "current_price": 12.2,
        "target_1": 12.0, "target_2": 14.0, "trade_health_score": 80,
    }
    data = build_trade_lifecycle(context)
    assert data["lifecycle_state"] == "SCALE"
    assert data["management_action"] == "TAKE_PARTIAL_AND_PROTECT"
    assert data["management_plan"]["reduce_position_pct"] == 40
    assert data["management_plan"]["recommended_stop"] == 10.0


def test_conflicting_flow_and_timeframes_force_defensive_management():
    context = base_context()
    context["multi_timeframe_intelligence"] = {"decision_gate": "TIMEFRAME_CONFLICT", "dominant_direction": "BEARISH"}
    context["flow_intelligence"] = {"decision_gate": "FLOW_CONFLICT", "institutional_bias": "BEARISH"}
    context["position"] = {"status": "OPEN", "quantity": 2, "entry_price": 10, "current_price": 10.5, "trade_health_score": 55}
    data = build_trade_lifecycle(context)
    assert data["lifecycle_state"] == "PROTECT"
    assert data["management_action"] == "REDUCE_AND_TIGHTEN"
    assert data["management_plan"]["reduce_position_pct"] == 50


def test_stop_trading_exits_open_position_and_never_calls_broker():
    context = base_context()
    context["session_intelligence"] = {"session": {"mode": "STOP_TRADING"}}
    context["position"] = {"status": "OPEN", "quantity": 1, "entry_price": 10, "current_price": 9.8}
    data = build_trade_lifecycle(context)
    assert data["lifecycle_state"] == "EXIT"
    assert data["management_action"] == "EXIT_POSITION"
    assert data["management_plan"]["reduce_position_pct"] == 100
    assert data["management_plan"]["order_submitted"] is False
