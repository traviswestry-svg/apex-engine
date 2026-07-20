"""Route registration and behavior tests for APEX 25.2."""
import datetime as dt

from flask import Flask

from engine import decision_outcome_forecast_v252 as forecast
from engine.decision_outcome_forecast_v252_routes import (
    REQUIRED_ROUTES,
    register_decision_outcome_forecast_v252_routes,
    verify_registered,
)


def _iso(offset=0):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=offset)).isoformat()


def _snapshot():
    now = _iso()
    return {
        "as_of": now, "symbol": "SPX", "direction": "BULLISH", "confidence": 80,
        "market_state": {"spx": 5200.0, "as_of": now, "bias": "BULLISH"},
        "institutional_intelligence": {"as_of": now, "institutional_bias": "BULLISH", "ici_score": 75},
        "flow_intelligence": {"as_of": now, "direction": "BULLISH", "score": 70},
        "dealer_positioning": {"as_of": now, "bias": "BULLISH"},
        "multi_timeframe": {"as_of": now, "alignment_score": 68},
        "market_memory": {"as_of": now},
        "historical_similarity": {"as_of": now},
        "confidence_calibration": {"as_of": now},
    }


def _app():
    app = Flask(__name__)
    register_decision_outcome_forecast_v252_routes(app, last_result_provider=_snapshot)
    return app


def test_all_required_routes_register():
    app = _app()
    assert verify_registered(app) == []
    assert len(REQUIRED_ROUTES) == 6


def test_status_route():
    client = _app().test_client()
    resp = client.get("/api/decision-forecast/status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["shadow_mode"] is True
    assert body["production_effect"] == "NONE"


def test_current_route_returns_forecast():
    client = _app().test_client()
    body = client.get("/api/decision-forecast/current").get_json()
    assert body["ok"] is True
    assert body["forecast"]["direction"] == "BULLISH"


def test_current_all_horizons():
    client = _app().test_client()
    body = client.get("/api/decision-forecast/current?all_horizons=true").get_json()
    assert set(body["forecasts"]).issuperset({"1m", "15m", "session"})


def test_scenarios_route_reconciles():
    client = _app().test_client()
    body = client.get("/api/decision-forecast/scenarios").get_json()
    assert sum(s["probability"] for s in body["scenarios"]) == 100


def test_analogs_route():
    client = _app().test_client()
    body = client.get("/api/decision-forecast/analogs").get_json()
    assert "comparable_sessions" in body
    assert body["production_effect"] == "NONE"


def test_evaluate_generate_path():
    client = _app().test_client()
    resp = client.post("/api/decision-forecast/evaluate", json=_snapshot())
    assert resp.status_code == 200
    assert resp.get_json()["forecast"]["direction"] == "BULLISH"


def test_evaluate_rejects_non_json():
    client = _app().test_client()
    resp = client.post("/api/decision-forecast/evaluate", data="notjson",
                       content_type="text/plain")
    assert resp.status_code == 400


def test_evaluate_immature_forecast_returns_409():
    client = _app().test_client()
    fc = forecast.build_forecast(_snapshot())["forecast"]
    resp = client.post("/api/decision-forecast/evaluate",
                       json={"forecast": fc, "realized": {"realized_direction": "BULLISH"}})
    assert resp.status_code == 409
    assert resp.get_json()["status"] == "NOT_MATURED"


def test_history_route(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_DECISION_FORECAST_DB", str(tmp_path / "r.db"))
    client = _app().test_client()
    body = client.get("/api/decision-forecast/history?limit=5").get_json()
    assert body["ok"] is True
    assert "forecasts" in body
