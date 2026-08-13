"""Tests for the APEX 26.1-26.5 Execution Intelligence Suite."""
import datetime as dt

import pytest
from flask import Flask

from engine import entry_optimization_v261 as entry_opt
from engine import contract_intelligence_v262 as contract_intel
from engine import liquidity_slippage_v263 as liquidity
from engine import position_sizing_v264 as sizing
from engine import dynamic_trade_management_v265 as management
from engine.execution_suite_v26x_routes import (
    REQUIRED_ROUTES, register_execution_suite_v26x_routes, verify_registered,
)


def _iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _snapshot(bid=2.00, ask=2.10, volume=5000, oi=12000, vix=16, hold=900, move=12):
    now = _iso()
    return {
        "as_of": now, "symbol": "SPX", "direction": "BULLISH", "confidence": 82,
        "market_regime": "TREND",
        "market_state": {"spx": 5200.0, "as_of": now, "bias": "BULLISH", "regime": "TREND",
                         "vwap": 5195.0, "structure_broken": False, "thesis_intact": True},
        "institutional_intelligence": {"as_of": now, "institutional_bias": "BULLISH", "ici_score": 78},
        "flow_intelligence": {"as_of": now, "direction": "BULLISH", "score": 72},
        "dealer_positioning": {"as_of": now, "bias": "BULLISH"},
        "multi_timeframe": {"as_of": now, "alignment_score": 70},
        "market_memory": {"as_of": now}, "historical_similarity": {"as_of": now},
        "confidence_calibration": {"as_of": now},
        "quote": {"bid": bid, "ask": ask, "volume": volume, "open_interest": oi, "age_seconds": 2},
        "momentum": {"score": 68},
        "greeks": {"gamma": 0.05, "theta": -0.4},
        "volatility": {"vix": vix},
        "forecast": {"expected_move_points": move, "expected_hold_seconds": hold,
                     "expected_risk_reward": 1.8, "expected_mae": 4.0},
        "entry_premium": 2.05, "stop_premium": 1.25,
        "portfolio": {"capital": 50000, "daily_loss_used": 0},
    }


# =========================== 26.3 Liquidity =============================== #
def test_liquidity_shape_and_safety():
    r = liquidity.analyze(_snapshot())
    assert r["production_effect"] == "NONE"
    assert r["liquidity_quality"] in liquidity.LIQUIDITY_TIERS
    assert r["recommended_order_type"] in liquidity.ORDER_TYPES
    assert 0 <= r["fill_probability"] <= 1


def test_liquidity_illiquid_prefers_conservative_order():
    r = liquidity.analyze(_snapshot(bid=1.0, ask=1.6, volume=20, oi=50))
    assert r["liquidity_quality"] in ("LOW", "ILLIQUID")
    assert r["recommended_order_type"] in ("LIMIT_OFFSET", "STOP_LIMIT")


def test_liquidity_slippage_grows_with_size():
    small = liquidity.analyze(_snapshot(), contracts=1)["estimated_slippage"]
    big = liquidity.analyze(_snapshot(), contracts=50)["estimated_slippage"]
    assert big >= small


def test_liquidity_deterministic():
    assert liquidity.analyze(_snapshot()) == liquidity.analyze(_snapshot())


# =========================== 26.1 Entry ================================== #
def test_entry_shape():
    r = entry_opt.optimize(_snapshot())
    assert r["production_effect"] == "NONE"
    assert r["recommended_action"] in entry_opt.ENTRY_ACTIONS
    assert r["recommended_order_type"] in liquidity.ORDER_TYPES
    for k in ("patience_score", "momentum_score", "confirmation_score",
              "pullback_probability", "chase_probability", "entry_confidence"):
        assert r[k] is not None


def test_entry_extended_waits_for_pullback():
    snap = _snapshot()
    snap["market_state"]["spx"] = 5200.0
    snap["market_state"]["vwap"] = 4850.0   # very extended
    snap["momentum"] = {"score": 85}
    r = entry_opt.optimize(snap)
    assert r["recommended_action"] == "WAIT_FOR_PULLBACK"


def test_entry_deterministic():
    assert entry_opt.optimize(_snapshot()) == entry_opt.optimize(_snapshot())


# =========================== 26.2 Contract =============================== #
def test_contract_shape():
    r = contract_intel.recommend(_snapshot())
    assert r["recommended_structure"] in contract_intel.STRUCTURES
    assert r["rationale"]
    assert r["production_effect"] == "NONE"


def test_contract_no_direction_high_vol_is_condor():
    snap = _snapshot(vix=26)
    snap["market_state"]["bias"] = "NEUTRAL"
    snap["direction"] = "NEUTRAL"
    r = contract_intel.recommend(snap)
    assert r["recommended_structure"] in ("IRON_CONDOR", "BUTTERFLY")


def test_contract_thin_liquidity_uses_defined_risk():
    snap = _snapshot(bid=1.0, ask=1.6, volume=20, oi=50)
    r = contract_intel.recommend(snap)
    assert r["recommended_structure"] == "DEBIT_SPREAD"


def test_contract_deterministic():
    assert contract_intel.recommend(_snapshot()) == contract_intel.recommend(_snapshot())


# =========================== 26.4 Sizing ================================= #
def test_sizing_enforces_limits():
    r = sizing.size(_snapshot(), entry_premium=2.0, stop_premium=1.99, confidence=95)
    assert r["recommended_contracts"] <= r["max_contracts_limit"]
    assert r["portfolio_risk_enforced"] is True


def test_sizing_respects_max_risk():
    r = sizing.size(_snapshot(), entry_premium=2.0, stop_premium=1.0, confidence=80)
    if r["estimated_dollar_risk"] is not None:
        assert r["estimated_dollar_risk"] <= r["effective_risk_cap"] + 1e-6


def test_sizing_daily_limit_blocks():
    snap = _snapshot()
    snap["portfolio"]["daily_loss_used"] = 999999
    r = sizing.size(snap, entry_premium=2.0, stop_premium=1.0, confidence=80)
    assert r["recommended_contracts"] == 0
    assert any("daily" in x.lower() for x in r["reasons"])


def test_sizing_kelly_capped():
    r = sizing.size(_snapshot(), entry_premium=2.0, stop_premium=1.0, confidence=99)
    assert r["kelly_fraction_capped"] <= 0.25


def test_sizing_portfolio_exposure():
    r = sizing.size(_snapshot(), entry_premium=2.0, stop_premium=1.0, confidence=80)
    assert r["portfolio_exposure_pct"] is not None


# =========================== 26.5 Management ============================= #
def _position(current=2.5, entry=2.0, stop=1.6, target=3.0, held=300, contracts=4):
    return {"position": {"entry_premium": entry, "current_premium": current, "stop_premium": stop,
                         "target_premium": target, "contracts": contracts, "held_seconds": held,
                         "max_hold_seconds": 23400}}


def test_management_break_even_at_1r():
    snap = {**_snapshot(), **_position(current=2.4, entry=2.0, stop=1.6)}  # ~1R
    r = management.manage(snap)
    actions = [a["action"] for a in r["recommended_actions"]]
    assert "BREAK_EVEN" in actions


def test_management_scale_out_at_1_5r():
    snap = {**_snapshot(), **_position(current=2.6, entry=2.0, stop=1.6)}  # 1.5R
    r = management.manage(snap)
    actions = [a["action"] for a in r["recommended_actions"]]
    assert "SCALE_OUT" in actions


def test_management_stop_hit_exits():
    snap = {**_snapshot(), **_position(current=1.5, entry=2.0, stop=1.6)}
    r = management.manage(snap)
    actions = [a["action"] for a in r["recommended_actions"]]
    assert "MOVE_STOP" in actions or "STRUCTURE_EXIT" in actions


def test_management_time_exit_near_max_hold():
    snap = {**_snapshot(), **_position(held=22000)}
    r = management.manage(snap)
    actions = [a["action"] for a in r["recommended_actions"]]
    assert "TIME_EXIT" in actions


def test_management_no_position_holds():
    r = management.manage(_snapshot())
    assert r["primary_action"] == "HOLD"


def test_management_never_modifies_orders():
    assert management.status()["modifies_orders"] is False


# =========================== Routes ===================================== #
def _app():
    app = Flask(__name__)
    register_execution_suite_v26x_routes(app, last_result_provider=_snapshot)
    return app


def test_all_routes_register():
    assert verify_registered(_app()) == []
    assert len(REQUIRED_ROUTES) == 14


def test_status_routes():
    c = _app().test_client()
    for base in ("entry-optimization", "contract-intelligence", "liquidity",
                 "position-sizing", "trade-management"):
        assert c.get(f"/api/{base}/status").status_code == 200


def test_current_routes():
    c = _app().test_client()
    for base in ("entry-optimization", "contract-intelligence", "liquidity", "trade-management"):
        assert c.get(f"/api/{base}/current").status_code == 200


def test_evaluate_routes():
    c = _app().test_client()
    for base in ("entry-optimization", "contract-intelligence", "liquidity", "trade-management"):
        assert c.post(f"/api/{base}/evaluate", json=_snapshot()).status_code == 200


def test_size_route():
    c = _app().test_client()
    resp = c.post("/api/position-sizing/size", json={"entry_premium": 2.0, "stop_premium": 1.0,
                                                     "confidence": 80, "portfolio": {"capital": 50000}})
    assert resp.status_code == 200
    assert resp.get_json()["portfolio_risk_enforced"] is True


def test_evaluate_rejects_non_json():
    c = _app().test_client()
    assert c.post("/api/liquidity/evaluate", data="x", content_type="text/plain").status_code == 400
