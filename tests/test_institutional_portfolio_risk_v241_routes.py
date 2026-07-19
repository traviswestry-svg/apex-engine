"""Route and Mission Control integration tests for APEX 24.1."""
from flask import Flask

from engine.institutional_portfolio_risk_v241_routes import (
    register_institutional_portfolio_risk_v241_routes,
)


def _client(last=None):
    app = Flask(__name__)
    register_institutional_portfolio_risk_v241_routes(app, last_result_provider=lambda: (last or {}))
    return app.test_client()


def test_status_route():
    c = _client()
    r = c.get("/api/portfolio-risk/status")
    assert r.status_code == 200
    assert r.get_json()["advisory_only"] is True


def test_exposure_and_budget_routes():
    last = {"account_equity": 60000, "underlying_price": 5000,
            "positions": [{"symbol": "SPX", "side": "LONG", "quantity": 1, "multiplier": 100,
                           "entry_price": 5, "mark_price": 6, "stop_price": 2.5,
                           "delta": 0.5, "option_type": "CALL"}]}
    c = _client(last)
    exp = c.get("/api/portfolio-risk/exposure").get_json()
    assert exp["ok"] is True
    assert "portfolio_delta" in exp["exposure"]
    bud = c.get("/api/portfolio-risk/budget").get_json()
    assert "risk_budget" in bud and "budget_manager" in bud


def test_evaluate_and_allocation_post():
    c = _client()
    body = {"account_equity": 60000, "positions": [],
            "signal": {"brain_confidence": 90, "forecast_confidence": 85,
                       "playbook_quality": 88, "execution_score": 84, "regime_confidence": 80}}
    ev = c.post("/api/portfolio-risk/evaluate", json=body).get_json()
    assert ev["status"] == "READY"
    al = c.post("/api/portfolio-risk/allocation", json=body).get_json()
    assert al["capital_allocation"]["grade"] == "FULL_SIZE"


def test_prioritize_post():
    c = _client()
    body = {"opportunities": [
        {"id": "A", "expected_value": 100, "max_risk": 50, "confidence": 80, "execution_quality": 80},
        {"id": "B", "expected_value": 5, "max_risk": 50, "confidence": 20, "execution_quality": 20},
    ]}
    res = c.post("/api/portfolio-risk/prioritize", json=body).get_json()["result"]
    assert res["ranked"][0]["id"] == "A"


def test_mission_control_includes_portfolio_panel():
    from engine.institutional_mission_control_v213 import build_mission_control
    mc = build_mission_control({"ticker": "SPX"})
    assert "PORTFOLIO_INTELLIGENCE" in mc["groups"]
    assert "portfolio_intelligence" in mc["drilldowns"]
    assert mc["drilldowns"]["portfolio_intelligence"] == "/api/portfolio-risk/status"


def test_evaluate_preserves_legacy_16_3_fields():
    # Existing 16.3 consumers read these top-level keys.
    c = _client()
    body = {"account_equity": 60000, "positions": [
        {"symbol": "SPX", "side": "LONG", "quantity": 1, "multiplier": 100,
         "entry_price": 10, "mark_price": 11, "stop_price": 9,
         "delta": 0.55, "gamma": 0.04, "theta": -0.25, "vega": 0.12}]}
    ev = c.post("/api/portfolio-risk/evaluate", json=body).get_json()
    assert ev["risk_state"] == "NORMAL"
    assert ev["net_greeks"]["delta"] == 55
    assert ev["total_open_risk"] == 100
    assert ev["advisory_only"] is True and ev["broker_effect"] == "NONE"
    assert ev["orders_changed"] is False


def test_evaluate_accepts_legacy_snapshot_envelope():
    c = _client()
    enveloped = {"snapshot": {"account_equity": 60000, "realized_pnl_today": -1000,
                              "policy": {"max_daily_loss": 1000}}}
    ev = c.post("/api/portfolio-risk/evaluate", json=enveloped).get_json()
    assert ev["risk_state"] in ("LOCKED_OUT", "BREACH")


def test_status_preserves_legacy_default_policy():
    c = _client()
    s = c.get("/api/portfolio-risk/status").get_json()
    assert "default_policy" in s  # 16.3 field preserved
    assert s["multi_account_ready"] is True  # 24.1 field added


def test_verify_registered_reports_missing_on_bare_app():
    from flask import Flask
    from engine.institutional_portfolio_risk_v241_routes import verify_registered, REQUIRED_ROUTES
    bare = Flask("bare")
    missing = verify_registered(bare)
    assert len(missing) == len(REQUIRED_ROUTES)
    ok = _client()  # registers on its own app
    # A freshly registered app should have zero missing canonical routes.
    from engine.institutional_portfolio_risk_v241_routes import (
        register_institutional_portfolio_risk_v241_routes)
    app2 = Flask("ok")
    register_institutional_portfolio_risk_v241_routes(app2, last_result_provider=lambda: {})
    assert verify_registered(app2) == []
