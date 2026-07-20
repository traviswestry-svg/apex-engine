"""Route tests for APEX 25.3 Adaptive Confidence Calibration."""
import datetime as dt

from flask import Flask

from engine import adaptive_confidence_calibration_v253 as calib
from engine.adaptive_confidence_calibration_v253_routes import (
    REQUIRED_ROUTES,
    register_adaptive_confidence_calibration_v253_routes,
    verify_registered,
)


def _iso(offset_days=0):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=offset_days)).isoformat()


def _history(n=60, win_rate=0.6, stated=80):
    wins = int(round(n * win_rate))
    return [{"stated_confidence": stated, "won": 1 if i < wins else 0,
             "realized_r": 1.0 if i < wins else -1.0, "direction": "BULLISH",
             "regime": "TREND", "observed_at": _iso(-n + i)} for i in range(n)]


def _snapshot():
    now = _iso()
    return {
        "as_of": now, "symbol": "SPX", "direction": "BULLISH", "confidence": 80,
        "market_regime": "TREND",
        "market_state": {"spx": 5200.0, "as_of": now, "bias": "BULLISH", "regime": "TREND"},
        "institutional_intelligence": {"as_of": now, "institutional_bias": "BULLISH", "ici_score": 75},
        "flow_intelligence": {"as_of": now, "direction": "BULLISH", "score": 70},
        "dealer_positioning": {"as_of": now, "bias": "BULLISH"},
        "multi_timeframe": {"as_of": now, "alignment_score": 68},
        "market_memory": {"as_of": now}, "historical_similarity": {"as_of": now},
        "confidence_calibration": {"as_of": now}, "calibration_history": _history(),
    }


def _app():
    app = Flask(__name__)
    register_adaptive_confidence_calibration_v253_routes(app, last_result_provider=_snapshot)
    return app


def test_all_required_routes_register():
    app = _app()
    assert verify_registered(app) == []
    assert len(REQUIRED_ROUTES) == 6


def test_status_route():
    body = _app().test_client().get("/api/confidence-calibration/status").get_json()
    assert body["shadow_mode"] is True
    assert body["production_effect"] == "NONE"


def test_current_route_layers():
    body = _app().test_client().get("/api/confidence-calibration/current").get_json()
    assert body["ok"] is True
    layers = body["calibration"]["confidence_layers"]
    assert layers["final_calibrated_confidence"] <= layers["integrity_ceiling"] + 1e-9


def test_curve_route():
    body = _app().test_client().get("/api/confidence-calibration/curve").get_json()
    assert "reliability_curve" in body
    assert "brier_score" in body


def test_buckets_route():
    body = _app().test_client().get("/api/confidence-calibration/buckets").get_json()
    assert "buckets" in body
    assert body["production_effect"] == "NONE"


def test_drift_route():
    body = _app().test_client().get("/api/confidence-calibration/drift").get_json()
    assert "drift" in body


def test_evaluate_route():
    resp = _app().test_client().post("/api/confidence-calibration/evaluate", json=_snapshot())
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_evaluate_rejects_non_json():
    resp = _app().test_client().post("/api/confidence-calibration/evaluate",
                                     data="x", content_type="text/plain")
    assert resp.status_code == 400
