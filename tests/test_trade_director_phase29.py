from engine.trade_director_portfolio_allocation import build_portfolio_allocation, build_portfolio_stress_test


def test_phase29_aggregates_exposure_and_reduces_concentrated_allocation():
    context = {
        "account_equity": 60000,
        "portfolio_risk_limit": 4000,
        "daily_loss_limit": 1500,
        "per_trade_risk_limit": 1200,
        "portfolio_positions": [
            {"trade_id": "A", "symbol": "SPX", "strategy": "CALL_DEBIT", "direction": "CALL", "risk_dollars": 1800, "delta_dollars": 5000},
            {"trade_id": "B", "symbol": "SPX", "strategy": "CALL_DEBIT", "direction": "CALL", "risk_dollars": 900, "delta_dollars": 2500},
        ],
        "strategy_orchestration": {"selected_strategy": "CALL_DEBIT", "confidence": 80},
        "institutional_decision_engine": {"decision": "CALL", "confidence": 80},
        "proposed_risk_dollars": 1200,
    }
    result = build_portfolio_allocation(context)
    assert result["version"] == "PHASE_29"
    assert result["portfolio_summary"]["total_risk_dollars"] == 2700
    assert result["candidate_allocation"]["recommended_risk_dollars"] < 1200
    assert "ELEVATED_SYMBOL_CONCENTRATION" in result["warnings"] or "SYMBOL_CONCENTRATION_LIMIT" in result["blockers"]
    assert result["controls"]["broker_access"] is False


def test_phase29_blocks_when_portfolio_budget_is_exhausted():
    result = build_portfolio_allocation({
        "portfolio_risk_limit": 1000,
        "portfolio_positions": [{"symbol": "SPX", "risk_dollars": 1000}],
        "proposed_risk_dollars": 500,
    })
    assert result["allocation_state"] == "BLOCKED"
    assert result["candidate_allocation"]["recommended_risk_dollars"] == 0
    assert "PORTFOLIO_RISK_BUDGET_EXHAUSTED" in result["blockers"]


def test_phase29_stress_test_is_advisory_only():
    result = build_portfolio_stress_test({
        "daily_loss_limit": 1000,
        "portfolio_positions": [{"symbol": "SPX", "risk_dollars": 500, "delta_dollars": 10000, "gamma_dollars": 2000}],
    }, shocks=[-2, 2])
    assert len(result["scenarios"]) == 2
    assert result["controls"]["order_submission"] is False
