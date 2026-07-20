"""Route and Mission Control integration tests for APEX 24.2."""
from flask import Flask, jsonify

from engine import institutional_governance as gov
from engine.institutional_replay_v242_routes import (
    register_institutional_replay_v242_routes, verify_registered, REQUIRED_ROUTES)


def _client(tmp_path, monkeypatch, legacy=None):
    monkeypatch.setattr(gov, "DB_PATH", str(tmp_path / "gov.db"))
    app = Flask(__name__)
    register_institutional_replay_v242_routes(
        app, last_result_provider=lambda: {"ticker": "SPX"},
        legacy_session_provider=legacy)
    return app, app.test_client()


def test_status_and_capture_and_session(tmp_path, monkeypatch):
    app, c = _client(tmp_path, monkeypatch)
    assert c.get("/api/replay/status").get_json()["read_only"] is True
    cap = c.post("/api/replay/capture", json={"session_key": "R1"}).get_json()
    assert cap["created"] is True
    sess = c.get(f"/api/replay/session?session_id={cap['session_id']}").get_json()
    assert sess["ok"] is True and "environment" in sess


def test_timeline_and_simulator_routes(tmp_path, monkeypatch):
    app, c = _client(tmp_path, monkeypatch)
    cap = c.post("/api/replay/capture", json={"session_key": "R2"}).get_json()
    tl = c.get(f"/api/replay/timeline?session_id={cap['session_id']}").get_json()
    assert tl["event_count"] > 0
    sim = c.post("/api/replay/simulator", json={
        "session_id": cap["session_id"],
        "scenario": {"type": "ALTERNATIVE_SIZING", "size_multiplier": 0.25}}).get_json()
    assert sim["history_modified"] is False


def test_session_route_preserves_legacy_contract(tmp_path, monkeypatch):
    called = {"hit": False}

    def legacy():
        called["hit"] = True
        return jsonify({"ok": True, "legacy": True, "frames": []})

    app, c = _client(tmp_path, monkeypatch, legacy=legacy)
    # Legacy params (date/ticker, no session_id) must route to the legacy provider.
    r = c.get("/api/replay/session?ticker=SPX&date=2026-07-18").get_json()
    assert called["hit"] is True
    assert r["legacy"] is True


def test_verify_registered(tmp_path, monkeypatch):
    monkeypatch.setattr(gov, "DB_PATH", str(tmp_path / "gov.db"))
    bare = Flask("bare")
    assert len(verify_registered(bare)) == len(REQUIRED_ROUTES)
    app, _ = _client(tmp_path, monkeypatch)
    assert verify_registered(app) == []


def test_mission_control_includes_replay_panel(tmp_path, monkeypatch):
    monkeypatch.setattr(gov, "DB_PATH", str(tmp_path / "gov.db"))
    from engine.institutional_mission_control_v213 import build_mission_control
    mc = build_mission_control({"ticker": "SPX"})
    assert "REPLAY_SIMULATOR" in mc["groups"]
    assert mc["drilldowns"]["replay_simulator"] == "/api/replay/status"
