"""Route tests for APEX 25.5 — including promotion authorization."""
import datetime as dt

from flask import Flask

from engine.institutional_validation_promotion_v255_routes import (
    REQUIRED_ROUTES,
    register_institutional_validation_promotion_v255_routes,
    verify_registered,
)


def _iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _snapshot():
    now = _iso()
    return {
        "as_of": now, "symbol": "SPX", "direction": "BULLISH", "confidence": 82,
        "market_regime": "TREND", "setup_family": "opening_drive", "decision_id": "dec_vrt_001",
        "market_state": {"spx": 5200.0, "as_of": now, "bias": "BULLISH", "regime": "TREND"},
        "institutional_intelligence": {"as_of": now, "institutional_bias": "BULLISH", "ici_score": 78},
        "flow_intelligence": {"as_of": now, "direction": "BULLISH", "score": 72},
        "dealer_positioning": {"as_of": now, "bias": "BULLISH"},
        "multi_timeframe": {"as_of": now, "alignment_score": 70},
        "market_memory": {"as_of": now}, "historical_similarity": {"as_of": now},
        "confidence_calibration": {"as_of": now},
    }


def _app():
    app = Flask(__name__)
    register_institutional_validation_promotion_v255_routes(app, last_result_provider=_snapshot)
    return app


def test_all_required_routes_register():
    assert verify_registered(_app()) == []
    assert len(REQUIRED_ROUTES) == 12


def test_read_routes_200():
    c = _app().test_client()
    for path in ("status", "current", "supervisor", "dashboard", "promotion"):
        assert c.get(f"/api/validation/{path}").status_code == 200


def test_dashboard_shadow_flag():
    body = _app().test_client().get("/api/validation/dashboard").get_json()
    assert body["shadow_mode_enforced"] is True
    assert body["production_effect"] == "NONE"


def test_lifecycle_route():
    body = _app().test_client().get("/api/validation/lifecycle/dec_x").get_json()
    assert "stages" in body or body.get("status") == "ORPHANED"


def test_replay_verify_route_404_on_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_DECISION_REVIEW_DB", str(tmp_path / "r.db"))
    assert _app().test_client().get("/api/validation/replay-verify/missing").status_code == 404


def test_report_route():
    c = _app().test_client()
    assert c.get("/api/validation/report/daily_validation").status_code == 200
    assert c.get("/api/validation/report/bogus").status_code == 404


def test_evaluate_route():
    resp = _app().test_client().post("/api/validation/evaluate", json=_snapshot())
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_evaluate_rejects_non_json():
    resp = _app().test_client().post("/api/validation/evaluate", data="x", content_type="text/plain")
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Promotion authorization
# --------------------------------------------------------------------------- #
def test_promotion_requires_token(monkeypatch):
    monkeypatch.delenv("APEX_OPERATOR_TOKEN", raising=False)
    resp = _app().test_client().post("/api/validation/promotion/forecast/propose", json={})
    assert resp.status_code == 503
    assert resp.get_json()["status"] == "AUTHZ_NOT_CONFIGURED"


def test_promotion_bad_token(monkeypatch):
    monkeypatch.setenv("APEX_OPERATOR_TOKEN", "secret")
    resp = _app().test_client().post("/api/validation/promotion/forecast/propose",
                                     json={}, headers={"X-APEX-Operator-Token": "wrong"})
    assert resp.status_code == 403


def test_promotion_valid_token_but_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_OPERATOR_TOKEN", "secret")
    monkeypatch.setenv("APEX_VALIDATION_DB", str(tmp_path / "v.db"))
    monkeypatch.setenv("APEX_DECISION_FORECAST_DB", str(tmp_path / "f.db"))
    resp = _app().test_client().post("/api/validation/promotion/forecast/propose",
                                     json={}, headers={"X-APEX-Operator-Token": "secret"})
    # Authorized, but forecast has no sample -> safety blocks -> 409.
    assert resp.status_code == 409
    assert resp.get_json()["status"] == "BLOCKED"
