from engine.trade_director_execution_certification import (
    build_execution_certification,
    build_order_intent,
    cancel_preview,
    confirm_preview,
    preview_order,
    reconcile_execution,
    reset_execution_certification_state,
    set_kill_switch,
    validate_order_intent,
)


def healthy_context():
    return {
        "symbol": "SPX", "market_session_valid": True, "data_fresh": True,
        "decision_authorized": True, "authorization_unexpired": True,
        "liquidity_acceptable": True, "spread_width_acceptable": True,
        "buying_power_sufficient": True,
        "authorization": {"authorization_id": "AUTH-1"},
        "portfolio_allocation": {"allocation_state": "ALLOCATABLE", "candidate_allocation": {"recommended_risk_dollars": 1000}, "portfolio_summary": {"total_risk_dollars": 0}},
        "candidate_order": {"option_symbol": "SPXW_TEST", "side": "BUY", "quantity": 1, "limit_price": 10.0},
        "broker_health": {"sandbox": True, "authenticated": True, "token_fresh": True, "account_access": True, "quote_access": True, "option_chain_access": True, "preview_supported": True, "order_status_supported": True, "cancel_replace_supported": True, "position_access": True, "balance_access": True},
    }


def setup_function():
    reset_execution_certification_state()


def test_order_intent_is_normalized_and_live_locked():
    intent = build_order_intent(healthy_context())
    assert intent["symbol"] == "SPX"
    assert intent["confirmation_required"] is True
    assert intent["intent_hash"]


def test_validation_fails_closed_when_data_stale():
    ctx = healthy_context(); ctx["data_fresh"] = False
    result = validate_order_intent(build_order_intent(ctx), ctx)
    assert result["valid"] is False
    assert "DATA_FRESH" in result["failures"]


def test_preview_requires_all_gates_and_never_submits_live():
    result = preview_order(healthy_context())
    assert result["ok"] is True
    assert result["state"] == "HUMAN_CONFIRMATION_REQUIRED"
    assert result["preview"]["live_submission_enabled"] is False


def test_confirmation_is_explicit_and_certification_only():
    preview = preview_order(healthy_context())["preview"]
    denied = confirm_preview(preview["preview_id"], "yes")
    assert denied["ok"] is False
    confirmed = confirm_preview(preview["preview_id"], "CONFIRM SANDBOX")
    assert confirmed["ok"] is True
    assert confirmed["confirmation"]["submission_state"] == "LOCKED_NO_BROKER_SUBMISSION"


def test_cancel_preview():
    preview = preview_order(healthy_context())["preview"]
    assert cancel_preview(preview["preview_id"])["preview"]["state"] == "CANCELLED"


def test_reconciliation_mismatch_activates_kill_switch():
    result = reconcile_execution({"internal_positions": [1], "broker_positions": []})
    assert result["status"] == "CRITICAL_MISMATCH"
    cert = build_execution_certification(healthy_context())
    assert cert["kill_switch"]["active"] is True
    assert "CRITICAL_RECONCILIATION_MISMATCH" in cert["blockers"]


def test_manual_kill_switch_blocks_preview():
    set_kill_switch(True, "manual test")
    result = preview_order(healthy_context())
    assert result["ok"] is False
    assert "KILL_SWITCH_INACTIVE" in result["validation"]["failures"]


def test_readiness_cannot_be_production_certified():
    cert = build_execution_certification(healthy_context())
    assert cert["readiness_state"] != "PRODUCTION_CERTIFIED"
    assert cert["controls"]["live_order_submission"] is False
