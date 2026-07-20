"""Route tests for APEX 26.0 Execution Intelligence Core."""
import datetime as dt

from flask import Flask

from engine.execution_intelligence_core_v260_routes import (
    REQUIRED_ROUTES,
    register_execution_intelligence_core_v260_routes,
    verify_registered,
)


def _iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _snapshot():
    now = _iso()
    return {
        "as_of": now, "symbol": "SPX", "direction": "BULLISH", "confidence": 82,
        "market_regime": "TREND",
        "market_state": {"spx": 5200.0, "as_of": now, "bias": "BULLISH", "regime": "TREND"},
        "institutional_intelligence": {"as_of": now, "institutional_bias": "BULLISH", "ici_score": 78},
        "flow_intelligence": {"as_of": now, "direction": "BULLISH", "score": 72},
        "dealer_positioning": {"as_of": now, "bias": "BULLISH"},
        "multi_timeframe": {"as_of": now, "alignment_score": 70},
        "market_memory": {"as_of": now}, "historical_similarity": {"as_of": now},
        "confidence_calibration": {"as_of": now},
        "quote": {"bid": 2.00, "ask": 2.10, "age_seconds": 2},
        "momentum": {"score": 68},
        "forecast": {"expected_move_points": 12.0, "expected_risk_reward": 1.8},
        "entry_premium": 2.05, "stop_premium": 1.25,
    }


def _app():
    app = Flask(__name__)
    register_execution_intelligence_core_v260_routes(app, last_result_provider=_snapshot)
    return app


def test_all_required_routes_register():
    assert verify_registered(_app()) == []
    assert len(REQUIRED_ROUTES) == 6


def test_status_route():
    body = _app().test_client().get("/api/execution/status").get_json()
    assert body["places_orders"] is False
    assert body["confirmation_gated"] is True


def test_readiness_route():
    body = _app().test_client().get("/api/execution/readiness").get_json()
    assert body["ok"] is True
    assert body["places_orders"] is False


def test_plan_route():
    body = _app().test_client().get("/api/execution/plan").get_json()
    assert body["ok"] is True
    assert body["guardrails"]["places_orders"] is False


def test_evaluate_route():
    resp = _app().test_client().post("/api/execution/evaluate", json=_snapshot())
    assert resp.status_code == 200
    assert resp.get_json()["guardrails"]["places_orders"] is False


def test_evaluate_rejects_non_json():
    resp = _app().test_client().post("/api/execution/evaluate", data="x", content_type="text/plain")
    assert resp.status_code == 400


def test_size_route_enforces_limits():
    resp = _app().test_client().post("/api/execution/size",
                                     json={"entry_premium": 2.00, "stop_premium": 1.00, "confidence": 90})
    assert resp.status_code == 200
    sizing = resp.get_json()["position_sizing"]
    assert sizing["recommended_contracts"] <= sizing["max_contracts_limit"]
    assert sizing["portfolio_risk_enforced"] is True


def test_size_rejects_non_json():
    resp = _app().test_client().post("/api/execution/size", data="x", content_type="text/plain")
    assert resp.status_code == 400


def test_grade_route():
    resp = _app().test_client().post("/api/execution/grade",
                                     json={"plan": {"entry": {"recommended_limit_price": 2.05,
                                                              "expected_slippage": 0.02}},
                                           "fill": {"fill_price": 2.06}})
    assert resp.status_code == 200
    assert resp.get_json()["production_effect"] == "NONE"
