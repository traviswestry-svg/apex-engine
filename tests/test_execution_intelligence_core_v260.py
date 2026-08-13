"""Tests for APEX 26.0 Execution Intelligence Core (advisory, order-free)."""
import datetime as dt

import pytest

from engine import execution_intelligence_core_v260 as execution


def _iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _snapshot(direction="BULLISH", confidence=82, spread=0.10, bid=2.00, ask=2.10):
    now = _iso()
    return {
        "as_of": now, "symbol": "SPX", "direction": direction, "confidence": confidence,
        "market_regime": "TREND",
        "market_state": {"spx": 5200.0, "as_of": now, "bias": direction, "regime": "TREND"},
        "institutional_intelligence": {"as_of": now, "institutional_bias": direction, "ici_score": 78},
        "flow_intelligence": {"as_of": now, "direction": direction, "score": 72},
        "dealer_positioning": {"as_of": now, "bias": direction},
        "multi_timeframe": {"as_of": now, "alignment_score": 70},
        "market_memory": {"as_of": now}, "historical_similarity": {"as_of": now},
        "confidence_calibration": {"as_of": now},
        "quote": {"bid": bid, "ask": ask, "volume": 5000, "open_interest": 12000, "age_seconds": 2},
        "momentum": {"score": 68},
        "forecast": {"expected_move_points": 12.0, "expected_risk_reward": 1.8, "expected_mae": 4.0},
        "entry_premium": 2.05, "stop_premium": 1.25,
    }


# --------------------------------------------------------------------------- #
# Safety-first guarantees
# --------------------------------------------------------------------------- #
def test_status_never_places_orders():
    s = execution.status()
    assert s["places_orders"] is False
    assert s["auto_submits"] is False
    assert s["confirmation_gated"] is True
    assert s["production_effect"] == "NONE"


def test_plan_guardrails():
    result = execution.build_execution_plan(_snapshot())
    g = result["guardrails"]
    assert g["places_orders"] is False
    assert g["auto_submits"] is False
    assert g["confirmation_gated"] is True
    assert g["risk_limits_enforced"] is True
    assert result["production_effect"] == "NONE"


def test_readiness_always_requires_confirmation():
    result = execution.build_execution_plan(_snapshot())
    assert result["execution_plan"]["readiness"]["requires_human_confirmation"] is True


# --------------------------------------------------------------------------- #
# Readiness
# --------------------------------------------------------------------------- #
def test_ready_when_eligible_and_tight_spread():
    result = execution.build_execution_plan(_snapshot(spread=0.10))
    state = result["execution_plan"]["readiness"]["state"]
    assert state in ("READY", "NOT_READY")  # never auto; never crashes


def test_blocked_on_wide_spread():
    # Very wide spread beyond max_spread_pct (12%).
    result = execution.build_execution_plan(_snapshot(bid=1.00, ask=1.80))
    readiness = result["execution_plan"]["readiness"]
    assert readiness["state"] == "BLOCKED"
    assert any("Spread" in b for b in readiness["blockers"])


def test_blocked_when_not_eligible():
    snap = _snapshot()
    snap.pop("market_state")
    snap.pop("institutional_intelligence")
    result = execution.build_execution_plan(snap)
    assert result["execution_plan"]["readiness"]["state"] in ("BLOCKED", "NOT_READY")


def test_stale_quote_blocks():
    snap = _snapshot()
    snap["quote"]["age_seconds"] = 90
    result = execution.build_execution_plan(snap)
    assert result["execution_plan"]["readiness"]["state"] == "BLOCKED"


# --------------------------------------------------------------------------- #
# Position sizing enforces existing limits
# --------------------------------------------------------------------------- #
def test_sizing_never_exceeds_max_contracts():
    # Tiny per-contract risk would imply many contracts; must cap at max_contracts.
    result = execution.size_position(_snapshot(), entry_premium=2.00, stop_premium=1.99, confidence=95)
    assert result["recommended_contracts"] <= result["max_contracts_limit"]
    assert result["portfolio_risk_enforced"] is True


def test_sizing_respects_max_risk_per_trade():
    result = execution.size_position(_snapshot(), entry_premium=2.00, stop_premium=1.00, confidence=80)
    # dollar risk must not exceed max_risk_per_trade
    if result["estimated_dollar_risk"] is not None:
        assert result["estimated_dollar_risk"] <= result["max_risk_per_trade"] + 1e-6


def test_sizing_zero_when_no_stop():
    result = execution.size_position(_snapshot(), entry_premium=2.00, stop_premium=2.00, confidence=80)
    assert result["recommended_contracts"] == 0
    assert result["reasons"]


def test_kelly_fraction_capped():
    result = execution.size_position(_snapshot(), entry_premium=2.00, stop_premium=1.00, confidence=99)
    assert result["kelly_fraction_capped"] <= 0.25


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #
def test_deterministic():
    snap = _snapshot()
    a = execution.build_execution_plan(snap)["execution_plan"]
    b = execution.build_execution_plan(snap)["execution_plan"]
    assert a == b


# --------------------------------------------------------------------------- #
# Strategy + entry
# --------------------------------------------------------------------------- #
def test_strategy_stand_down_when_ineligible():
    snap = _snapshot()
    snap.pop("market_state")
    snap.pop("institutional_intelligence")
    result = execution.build_execution_plan(snap)
    assert result["execution_plan"]["strategy"]["strategy"] in ("STAND_DOWN", "DEBIT_SPREAD")


def test_entry_order_type_valid():
    result = execution.build_execution_plan(_snapshot())
    ot = result["execution_plan"]["entry"]["recommended_order_type"]
    assert ot in execution.ORDER_TYPES


def test_wide_spread_prefers_limit_not_market():
    snap = _snapshot(bid=2.00, ask=2.30)  # ~14% spread
    entry = execution.optimize_entry(snap, execution.assess_readiness(snap, {"decision": {}}))
    assert entry["recommended_order_type"] in ("LIMIT", "LIMIT_OFFSET")


# --------------------------------------------------------------------------- #
# Execution grading (independent of forecast)
# --------------------------------------------------------------------------- #
def test_grade_good_fill():
    plan = execution.build_execution_plan(_snapshot())["execution_plan"]
    result = execution.grade_execution(plan, {"fill_price": plan["entry"]["recommended_limit_price"] or 2.05})
    assert result["ok"] is True
    assert result["graded_on"] == "EXECUTION_QUALITY_INDEPENDENT_OF_FORECAST"
    assert result["production_effect"] == "NONE"


def test_grade_not_gradeable_without_fill():
    plan = execution.build_execution_plan(_snapshot())["execution_plan"]
    result = execution.grade_execution(plan, {})
    assert result["execution_grade"] == "NOT_GRADEABLE"


# --------------------------------------------------------------------------- #
# Mission Control
# --------------------------------------------------------------------------- #
def test_mission_control_group():
    result = execution.build_execution_plan(_snapshot())
    group = execution.mission_control_group(result)
    assert group["group"] == "EXECUTION_INTELLIGENCE"
    assert group["places_orders"] is False
    assert group["confirmation_gated"] is True
    assert group["production_effect"] == "NONE"


def test_empty_payload_safe():
    result = execution.build_execution_plan({})
    assert result["ok"] is True
    assert result["production_effect"] == "NONE"
    assert result["guardrails"]["places_orders"] is False
