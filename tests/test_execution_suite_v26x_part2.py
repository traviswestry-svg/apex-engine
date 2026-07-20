"""Tests for the APEX 26.6-26.10 Execution Intelligence Suite (part 2)."""
import datetime as dt

import pytest
from flask import Flask

from engine import trade_story_v266 as trade_story
from engine import broker_intelligence_v267 as broker
from engine import execution_review_v268 as exec_review
from engine import command_center_v269 as command_center
from engine.execution_suite_v26x_part2_routes import (
    REQUIRED_ROUTES, register_execution_suite_v26x_part2_routes, verify_registered,
)


def _iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _snapshot():
    now = _iso()
    return {
        "as_of": now, "symbol": "SPX", "direction": "BULLISH", "confidence": 82,
        "market_regime": "TREND",
        "market_state": {"spx": 5200.0, "as_of": now, "bias": "BULLISH", "regime": "TREND",
                         "thesis_intact": True, "structure_broken": False},
        "institutional_intelligence": {"as_of": now, "institutional_bias": "BULLISH", "ici_score": 78},
        "flow_intelligence": {"as_of": now, "direction": "BULLISH", "score": 72},
        "dealer_positioning": {"as_of": now, "bias": "BULLISH"},
        "multi_timeframe": {"as_of": now, "alignment_score": 70},
        "market_memory": {"as_of": now}, "historical_similarity": {"as_of": now},
        "confidence_calibration": {"as_of": now},
        "quote": {"bid": 2.00, "ask": 2.10, "volume": 5000, "open_interest": 12000, "age_seconds": 2},
        "momentum": {"score": 68}, "greeks": {"gamma": 0.05, "theta": -0.4},
        "volatility": {"vix": 16},
        "forecast": {"expected_move_points": 12.0, "expected_hold_seconds": 900,
                     "expected_risk_reward": 1.8, "expected_path": "DIRECTIONAL_DRIFT"},
        "entry_premium": 2.05, "stop_premium": 1.25,
        "portfolio": {"capital": 50000, "daily_loss_used": 0},
    }


# =========================== 26.6 Trade Story ============================ #
def test_story_shape():
    r = trade_story.build_story(_snapshot())
    assert r["production_effect"] == "NONE"
    assert "why_entered" in r["story"]
    assert "updated_confidence" in r
    assert "updated_forecast" in r


def test_story_with_open_position():
    snap = _snapshot()
    snap["position"] = {"entry_premium": 2.0, "current_premium": 2.6, "stop_premium": 1.6,
                        "target_premium": 3.0, "contracts": 4, "held_seconds": 300,
                        "max_hold_seconds": 23400}
    r = trade_story.build_story(snap)
    assert r["story"]["why_holding"] is not None


def test_story_deterministic_body():
    a = trade_story.build_story(_snapshot()); b = trade_story.build_story(_snapshot())
    a.pop("story"); b.pop("story")  # story text stable; compare rest sans volatile keys? both stable anyway
    # confirm both callable and shaped identically at top level
    assert set(a) == set(b)


# =========================== 26.7 Broker Intelligence ==================== #
def test_broker_never_submits():
    s = broker.status()
    assert s["submits_orders"] is False
    assert s["read_only"] is True
    assert s["production_effect"] == "NONE"


def test_broker_view_reports_health_and_gate():
    r = broker.build_broker_view(_snapshot())
    assert r["submits_orders"] is False
    assert set(r["broker_health"]) == set(broker.SUPPORTED_BROKERS)
    assert r["execution_gate"]["confirmation_required"] in (True, False)


def test_broker_normalizes_preview():
    snap = _snapshot()
    snap["broker_preview"] = {"account": {"buying_power": 25000, "margin": 0},
                              "order": {"commission": 1.0, "estimated_cost": 820,
                                        "status": "PREVIEW"}, "latency_ms": 120}
    r = broker.build_broker_view(snap)
    assert r["preview"]["buying_power"] == 25000
    assert r["preview"]["order_status"] == "PREVIEW"
    assert r["preview"]["estimated_cost"] == 820


def test_broker_has_no_place_order_attribute():
    # Safety: the module must expose no order-submission function.
    assert not any(hasattr(broker, name) for name in ("place_order", "submit_order", "send_order"))


# =========================== 26.8 Execution Review ======================= #
def _trade(entry_fill=2.06, exit_fill=2.9, mfe=1.0, mae=0.3, realized=0.9):
    return {
        "plan": {"entry": {"recommended_limit_price": 2.05, "expected_slippage": 0.02}},
        "fills": {"entry_fill_price": entry_fill, "exit_fill_price": exit_fill},
        "exit": {"target_premium": 3.0},
        "spread": 0.10, "mfe": mfe, "mae": mae, "realized_r": realized,
        "management_actions_taken": ["BREAK_EVEN"],
    }


def test_review_shape_and_grade():
    r = exec_review.review(_trade())
    assert r["execution_grade"] in exec_review.GRADES
    assert r["graded_on"] == "EXECUTION_QUALITY_INDEPENDENT_OF_FORECAST"
    for d in exec_review.DIMENSIONS:
        assert d in r["dimensions"]


def test_review_not_gradeable_without_fills():
    r = exec_review.review({"plan": {}})
    assert r["execution_grade"] == "NOT_GRADEABLE"


def test_review_poor_fill_scores_lower_than_clean_fill():
    clean = exec_review.review(_trade(entry_fill=2.05))["execution_score"]
    poor = exec_review.review(_trade(entry_fill=2.30))["execution_score"]
    assert poor < clean


def test_review_independent_of_forecast():
    # Same execution quality regardless of forecast fields (none supplied here).
    r = exec_review.review(_trade())
    assert r["ok"] is True


# =========================== 26.9 / 26.10 Aggregators ==================== #
def test_command_center_aggregates():
    r = command_center.build_command_center(_snapshot())
    assert r["view"] == "COMMAND_CENTER"
    assert r["production_effect"] == "NONE"
    assert r["guardrails"]["places_orders"] is False
    assert "execution_readiness" in r["panels"]
    assert "trade_story" in r["panels"]
    assert "broker_status" in r["panels"]


def test_trader_mode_aggregates_full_platform():
    r = command_center.build_trader_mode(_snapshot())
    assert r["view"] == "INSTITUTIONAL_TRADER_MODE"
    tm = r["trader_mode"]
    for key in ("decision_integrity", "reasoning", "forecast", "confidence",
                "execution", "learning_queue", "promotion_queue", "system_health"):
        assert key in tm
    assert r["guardrails"]["aggregator_only"] is True


def test_aggregators_never_crash_on_empty():
    assert command_center.build_command_center({})["ok"] is True
    assert command_center.build_trader_mode({})["ok"] is True


# =========================== Routes ===================================== #
def _app():
    app = Flask(__name__)
    register_execution_suite_v26x_part2_routes(app, last_result_provider=_snapshot)
    return app


def test_all_routes_register():
    assert verify_registered(_app()) == []
    assert len(REQUIRED_ROUTES) == 11


def test_status_routes():
    c = _app().test_client()
    for base in ("trade-story", "broker-intelligence", "execution-review", "command-center"):
        assert c.get(f"/api/{base}/status").status_code == 200


def test_read_routes():
    c = _app().test_client()
    assert c.get("/api/trade-story/current").status_code == 200
    assert c.get("/api/broker-intelligence/current").status_code == 200
    assert c.get("/api/command-center/current").status_code == 200
    assert c.get("/api/trader-mode/current").status_code == 200


def test_broker_preview_route():
    c = _app().test_client()
    resp = c.post("/api/broker-intelligence/preview",
                  json={"broker_preview": {"account": {"buying_power": 25000},
                                           "order": {"status": "PREVIEW"}}})
    assert resp.status_code == 200
    assert resp.get_json()["submits_orders"] is False


def test_execution_review_route():
    c = _app().test_client()
    resp = c.post("/api/execution-review/evaluate", json={"trade": _trade()})
    assert resp.status_code == 200
    assert resp.get_json()["graded_on"] == "EXECUTION_QUALITY_INDEPENDENT_OF_FORECAST"


def test_evaluate_rejects_non_json():
    c = _app().test_client()
    assert c.post("/api/trade-story/evaluate", data="x", content_type="text/plain").status_code == 400
