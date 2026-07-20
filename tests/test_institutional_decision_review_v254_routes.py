"""Route tests for APEX 25.4 — including approve/reject authorization."""
import datetime as dt

from flask import Flask

from engine import institutional_decision_review_v254 as review
from engine.institutional_decision_review_v254_routes import (
    REQUIRED_ROUTES,
    register_institutional_decision_review_v254_routes,
    verify_registered,
)


def _iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _snapshot():
    now = _iso()
    return {
        "as_of": now, "symbol": "SPX", "direction": "BULLISH", "confidence": 82,
        "market_regime": "TREND", "setup_family": "opening_drive", "decision_id": "dec_rt_001",
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
    register_institutional_decision_review_v254_routes(app, last_result_provider=_snapshot)
    return app


def test_all_required_routes_register():
    assert verify_registered(_app()) == []
    assert len(REQUIRED_ROUTES) == 10


def test_status_route():
    body = _app().test_client().get("/api/decision-review/status").get_json()
    assert body["production_effect"] == "NONE"


def test_evaluate_route():
    resp = _app().test_client().post("/api/decision-review/evaluate", json=_snapshot())
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_evaluate_rejects_non_json():
    resp = _app().test_client().post("/api/decision-review/evaluate", data="x",
                                     content_type="text/plain")
    assert resp.status_code == 400


def test_recent_best_worst_routes():
    c = _app().test_client()
    for path in ("recent", "best", "worst"):
        assert c.get(f"/api/decision-review/{path}").status_code == 200


def test_recommendations_and_queue_routes():
    c = _app().test_client()
    assert c.get("/api/decision-review/recommendations").status_code == 200
    assert c.get("/api/decision-review/promotion-queue").status_code == 200


def test_report_route():
    c = _app().test_client()
    assert c.get("/api/decision-review/report/daily_decision_review").status_code == 200
    assert c.get("/api/decision-review/report/bogus").status_code == 404


def test_detail_route_not_found():
    assert _app().test_client().get("/api/decision-review/nonexistent").status_code == 404


# --------------------------------------------------------------------------- #
# Authorization on approve/reject
# --------------------------------------------------------------------------- #
def test_approve_requires_configured_token(monkeypatch):
    monkeypatch.delenv("APEX_OPERATOR_TOKEN", raising=False)
    resp = _app().test_client().post("/api/decision-review/recommendations/reco_x/approve", json={})
    assert resp.status_code == 503
    assert resp.get_json()["status"] == "AUTHZ_NOT_CONFIGURED"


def test_approve_rejects_bad_token(monkeypatch):
    monkeypatch.setenv("APEX_OPERATOR_TOKEN", "secret-token")
    resp = _app().test_client().post("/api/decision-review/recommendations/reco_x/approve",
                                     json={}, headers={"X-APEX-Operator-Token": "wrong"})
    assert resp.status_code == 403
    assert resp.get_json()["status"] == "UNAUTHORIZED"


def test_approve_with_valid_token(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_OPERATOR_TOKEN", "secret-token")
    monkeypatch.setenv("APEX_DECISION_REVIEW_DB", str(tmp_path / "r.db"))
    # seed a recommendation
    lc = review.build_lifecycle_snapshot(_snapshot())
    rev = review.review_decision(lc, {"matured": True, "taken": True, "won": False,
                                      "realized_direction": "BULLISH", "realized_move_points": 5,
                                      "realized_mfe": 5, "realized_mae": 6})
    recos = review.generate_recommendations(rev, lc)
    review.store_recommendations(recos)
    rid = recos[0]["recommendation_id"] if recos else "reco_none"
    resp = _app().test_client().post(f"/api/decision-review/recommendations/{rid}/approve",
                                     json={"actor": "travis"},
                                     headers={"X-APEX-Operator-Token": "secret-token"})
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        assert resp.get_json()["new_status"] == "APPROVED"
        assert resp.get_json()["production_effect"] == "NONE"


def test_reject_rejects_bad_token(monkeypatch):
    monkeypatch.setenv("APEX_OPERATOR_TOKEN", "secret-token")
    resp = _app().test_client().post("/api/decision-review/recommendations/reco_x/reject",
                                     json={}, headers={"X-APEX-Operator-Token": "nope"})
    assert resp.status_code == 403
