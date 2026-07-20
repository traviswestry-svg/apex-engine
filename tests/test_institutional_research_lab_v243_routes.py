"""Route and Mission Control integration tests for APEX 24.3."""
from flask import Flask

from engine import institutional_governance as gov
from engine.institutional_research_lab_v243_routes import (
    register_institutional_research_lab_v243_routes, verify_registered, REQUIRED_ROUTES)


def _client(tmp_path, monkeypatch, legacy=None):
    monkeypatch.setattr(gov, "DB_PATH", str(tmp_path / "gov.db"))
    app = Flask(__name__)
    register_institutional_research_lab_v243_routes(app, legacy_status_provider=legacy)
    return app.test_client()


def test_status_merges_legacy_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch, legacy=lambda: {"institutional_similarity": {"x": 1},
                                                       "legacy_marker": True})
    s = c.get("/api/research/status").get_json()
    assert s["legacy_marker"] is True  # preserved legacy field
    assert s["offline_research_only"] is True  # 24.3 field
    assert s["production_settings_mutation_enabled"] is False


def test_strategies_and_performance_routes(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/api/research/strategies").get_json()["ok"] is True
    assert c.get("/api/research/performance").get_json()["ok"] is True


def test_experiment_lifecycle_via_routes(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    created = c.post("/api/research/experiments", json={
        "name": "R_EXP", "strategy": "MOMENTUM", "hypothesis": "h",
        "baseline_params": {"stop": 1.0}}).get_json()
    assert created["created"] is True
    eid = created["experiment_id"]
    rev = c.post("/api/research/experiments/revision", json={
        "experiment_id": eid, "params": {"stop": 0.5},
        "before_metrics": {"expectancy": 10}, "after_metrics": {"expectancy": 25}}).get_json()
    assert rev["before_after"]["delta"]["expectancy"] == 15
    listing = c.get("/api/research/experiments").get_json()
    assert listing["count"] == 1
    detail = c.get(f"/api/research/experiments?experiment_id={eid}").get_json()
    assert detail["current_version"] == 2


def test_analytics_route(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    res = c.post("/api/research/analytics", json={"trades": [
        {"pnl": 100, "regime": "TREND"}, {"pnl": -40, "regime": "CHOP"}]}).get_json()
    assert res["overall"]["sample"] == 2


def test_verify_registered(tmp_path, monkeypatch):
    monkeypatch.setattr(gov, "DB_PATH", str(tmp_path / "gov.db"))
    bare = Flask("bare")
    assert len(verify_registered(bare)) == len(REQUIRED_ROUTES)
    c = _client(tmp_path, monkeypatch)
    # the client's app registered all routes
    app = Flask("ok")
    register_institutional_research_lab_v243_routes(app, legacy_status_provider=None)
    assert verify_registered(app) == []


def test_mission_control_includes_research_panel(tmp_path, monkeypatch):
    monkeypatch.setattr(gov, "DB_PATH", str(tmp_path / "gov.db"))
    from engine.institutional_mission_control_v213 import build_mission_control
    mc = build_mission_control({"ticker": "SPX"})
    assert "STRATEGY_RESEARCH" in mc["groups"]
    assert mc["drilldowns"]["strategy_research"] == "/api/research/status"
