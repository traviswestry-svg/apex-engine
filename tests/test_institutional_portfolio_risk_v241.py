"""Tests for APEX 24.1 Institutional Portfolio & Risk Intelligence."""
import os

from engine import institutional_portfolio_risk_v241 as pr


def _long_call(**kw):
    base = {"symbol": "SPX", "side": "LONG", "quantity": 1, "multiplier": 100,
            "entry_price": 5.0, "mark_price": 6.0, "stop_price": 2.5,
            "delta": 0.5, "gamma": 0.02, "theta": -0.3, "vega": 0.1,
            "option_type": "CALL", "playbook_id": "PB_A", "strategy_family": "MOMENTUM"}
    base.update(kw)
    return base


def test_status_is_advisory_and_multi_account_ready():
    s = pr.status()
    assert s["status"] == "READY"
    assert s["advisory_only"] is True
    assert s["multi_account_ready"] is True
    assert s["broker_order_submission_enabled"] is False
    assert s["automatic_position_resizing_enabled"] is False
    assert "APEX_DAILY_RISK_BUDGET" in s["governed_variables"].values()


def test_resolve_risk_budget_reports_sources_and_env_override(monkeypatch):
    monkeypatch.delenv("APEX_DAILY_RISK_BUDGET", raising=False)
    b = pr.resolve_risk_budget({})
    assert b["daily_risk_budget"] == 1500.0
    assert b["sources"]["daily_risk_budget"] == "GOVERNED_DEFAULT"
    b2 = pr.resolve_risk_budget({"APEX_DAILY_RISK_BUDGET": "2222"})
    assert b2["daily_risk_budget"] == 2222.0
    assert b2["sources"]["daily_risk_budget"] == "ENVIRONMENT"


def test_exposure_greeks_and_directional_and_premium():
    snap = {"account_equity": 60000, "underlying_price": 5000,
            "positions": [_long_call(), _long_call(delta=0.4, playbook_id="PB_B")]}
    out = pr.evaluate_portfolio(snap)
    exp = out["exposure"]
    # delta scaled by qty*multiplier: (0.5+0.4)*100 = 90
    assert abs(exp["portfolio_delta"] - 90.0) < 1e-6
    assert exp["net_direction"] == "NET_LONG"
    # directional notional = net_delta * underlying_price
    assert abs(exp["net_directional_exposure"] - 90.0 * 5000) < 1e-3
    # both long => premium at risk equals total market value
    assert exp["premium_at_risk"] == exp["total_market_value"] > 0
    assert exp["buying_power_utilization_pct"] > 0
    assert exp["remaining_deployable_capital"] >= 0


def test_budget_manager_flags_concurrency_breach():
    positions = [_long_call(position_id=f"P{i}") for i in range(5)]
    snap = {"account_equity": 60000, "positions": positions,
            "env": {"APEX_MAX_CONCURRENT_POSITIONS": "3"}}
    out = pr.evaluate_portfolio(snap)
    assert "MAX_CONCURRENT_POSITIONS" in out["budget_manager"]["breached_budgets"]
    assert out["budget_manager"]["state"] == "BUDGET_BREACH"
    assert out["portfolio_state"] == "RESTRICTED"


def test_correlation_detects_duplicate_direction_and_playbook():
    positions = [_long_call(), _long_call()]  # same bullish direction + same playbook
    corr = pr.correlation_intelligence(positions)
    codes = {w["code"] for w in corr["warnings"]}
    assert "DUPLICATE_DIRECTIONAL_EXPOSURE" in codes
    assert "DUPLICATE_PLAYBOOK" in codes
    assert "DUPLICATE_STRATEGY_FAMILY" in codes


def test_correlation_detects_call_concentration():
    positions = [_long_call(playbook_id="A", strategy_family="X"),
                 _long_call(playbook_id="B", strategy_family="Y", delta=-0.1)]
    corr = pr.correlation_intelligence(positions)
    codes = {w["code"] for w in corr["warnings"]}
    assert "EXCESS_CALL_CONCENTRATION" in codes


def test_capital_allocation_full_size_on_strong_signal():
    snap = {"account_equity": 60000, "positions": [],
            "signal": {"brain_confidence": 90, "forecast_confidence": 85,
                       "playbook_quality": 88, "execution_score": 84,
                       "regime_confidence": 80}}
    out = pr.evaluate_portfolio(snap)
    alloc = out["capital_allocation"]
    assert alloc["grade"] == "FULL_SIZE"
    assert alloc["size_multiplier"] == 1.0
    assert alloc["advisory_only"] is True


def test_capital_allocation_no_new_risk_on_lockout():
    # Force a hard daily-loss lockout via the base engine policy.
    snap = {"account_equity": 60000, "realized_pnl_today": -5000,
            "positions": [_long_call()],
            "policy": {"max_daily_loss": 1000},
            "signal": {"brain_confidence": 99, "forecast_confidence": 99,
                       "playbook_quality": 99, "execution_score": 99,
                       "regime_confidence": 99}}
    out = pr.evaluate_portfolio(snap)
    assert out["base_assessment"]["risk_state"] in ("LOCKED_OUT", "BREACH")
    assert out["capital_allocation"]["grade"] == "NO_NEW_RISK"
    assert out["capital_allocation"]["size_multiplier"] == 0.0


def test_opportunity_prioritization_ranks_and_rewards_diversification():
    opps = [
        {"id": "HIGH", "expected_value": 200, "max_risk": 100, "capital_required": 100,
         "confidence": 90, "execution_quality": 90, "direction": "BEARISH",
         "strategy_family": "MEAN_REVERSION"},
        {"id": "LOW", "expected_value": 10, "max_risk": 100, "capital_required": 100,
         "confidence": 30, "execution_quality": 30, "direction": "BULLISH",
         "strategy_family": "MOMENTUM"},
    ]
    book = [_long_call()]  # bullish momentum already held
    result = pr.prioritize_opportunities(opps, current_book=book)
    ranked = result["ranked"]
    assert ranked[0]["id"] == "HIGH"
    assert ranked[0]["rank"] == 1
    # HIGH diverges from the book (bearish + different family) => full diversification
    assert ranked[0]["components"]["diversification_benefit"] == 100.0
    # LOW duplicates both direction and family => zero diversification
    low = next(r for r in ranked if r["id"] == "LOW")
    assert low["components"]["diversification_benefit"] == 0.0


def test_multi_account_folding_aggregates_positions():
    snap = {"account_equity": 120000, "underlying_price": 5000, "accounts": [
        {"account_id": "A", "positions": [_long_call()]},
        {"account_id": "B", "positions": [_long_call(delta=0.3)]},
    ]}
    out = pr.evaluate_portfolio(snap)
    assert out["account_ids"] == ["A", "B"]
    assert out["base_assessment"]["open_position_count"] == 2
    assert abs(out["exposure"]["portfolio_delta"] - (0.5 + 0.3) * 100) < 1e-6


def test_build_portfolio_intelligence_safe_on_empty():
    out = pr.build_portfolio_intelligence({})
    assert out["ok"] is True
    assert out["portfolio_state"] in ("NORMAL", "ELEVATED", "RESTRICTED")
    assert out["opportunities"]["count"] == 0


def test_evaluate_never_reports_broker_effect():
    out = pr.evaluate_portfolio({"positions": [_long_call()]})
    assert out["production_effect"] == "NONE"
    assert out["broker_order_submission_enabled"] is False
    assert out["automatic_position_resizing_enabled"] is False
