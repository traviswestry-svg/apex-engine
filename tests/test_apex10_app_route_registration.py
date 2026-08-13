"""Regression guard: production app must expose every APEX 10 API family."""
import app as apex_app


def test_production_app_registers_apex10_routes():
    rules = {rule.rule for rule in apex_app.app.url_map.iter_rules()}
    expected = {
        "/api/institutional_state",
        "/api/evidence_graph",
        "/api/decision_trace",
        "/api/market_story",
        "/api/apex10/evidence",
        "/api/system/readiness",
        "/api/system/metrics",
        "/api/learning/calibration",
        "/api/learning/proposals",
        "/api/learning/policies/<policy_id>/promote",
        "/api/learning/outcomes/<sample_id>",
        "/api/learning/apply",
        "/api/similarity/<sample_id>",
        "/api/provenance/<sample_id>",
    }
    assert expected <= rules


def test_apex10_readiness_and_state_are_not_404():
    client = apex_app.app.test_client()
    assert client.get("/api/system/readiness").status_code in {200, 503}
    assert client.get("/api/institutional_state?ticker=SPX").status_code == 200
    assert client.get("/api/apex10/evidence?ticker=SPX").status_code == 200
