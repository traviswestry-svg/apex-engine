import json
from pathlib import Path

from engine.market_memory_engine_v220 import (
    VERSION, attach_outcome, capture_snapshot, diagnostics, find_similar,
    list_sessions, status,
)


def sample(**overrides):
    data = {
        "ticker": "SPX", "session": "RTH", "data_fresh": True,
        "institutional_decision": {"decision": "TRADE_CANDIDATE", "bias": "BULLISH", "regime": "EXPANSION", "confidence": 84},
        "institutional_market_structure": {"opening_type": "OPEN_DRIVE", "auction_state": "ACCEPTANCE_ABOVE_VALUE", "value_migration": "RISING", "poc_migration": "RISING"},
        "dealer_positioning": {"regime": "SHORT_GAMMA", "bias": "BULLISH"},
        "options_flow_intelligence": {"bias": "BULLISH"},
        "institutional_probability": {"trend_day_probability": 76, "range_day_probability": 24},
        "volume_profile": {"poc": 6300, "vah": 6310, "val": 6290},
        "api_key": "DO-NOT-STORE",
    }
    data.update(overrides)
    return data


def test_capture_locked_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("APEX_MARKET_MEMORY_CAPTURE_ENABLED", raising=False)
    monkeypatch.setenv("APEX_MARKET_MEMORY_DB", str(tmp_path / "m.db"))
    assert capture_snapshot(sample())["state"] == "LOCKED"


def test_capture_redacts_and_indexes(monkeypatch, tmp_path):
    db = tmp_path / "m.db"
    monkeypatch.setenv("APEX_MARKET_MEMORY_CAPTURE_ENABLED", "true")
    monkeypatch.setenv("APEX_MARKET_MEMORY_DB", str(db))
    result = capture_snapshot(sample(), observed_at="2026-07-17T14:00:00+00:00")
    assert result["captured"] is True
    raw = db.read_bytes()
    assert b"DO-NOT-STORE" not in raw
    sessions = list_sessions(path=str(db))
    assert sessions["count"] == 1
    assert sessions["sessions"][0]["features"]["bias"] == "BULLISH"


def test_similarity_and_lookahead(monkeypatch, tmp_path):
    db = str(tmp_path / "m.db")
    capture_snapshot(sample(), observed_at="2026-07-15T14:00:00+00:00", path=db, force=True)
    capture_snapshot(sample(institutional_decision={"decision":"WATCH","bias":"BEARISH","regime":"BALANCE","confidence":60}), observed_at="2026-07-16T14:00:00+00:00", path=db, force=True)
    result = find_similar(sample(), path=db, before="2026-07-16T00:00:00+00:00")
    assert result["look_ahead_protected"] is True
    assert result["matches"][0]["session_date"] == "2026-07-15"


def test_outcome_writes_locked_and_force_supported(tmp_path):
    db = str(tmp_path / "m.db")
    item = capture_snapshot(sample(), path=db, force=True)
    assert attach_outcome(item["memory_id"], {"result":"WIN"}, path=db)["state"] == "LOCKED"
    assert attach_outcome(item["memory_id"], {"result":"WIN", "secret":"x"}, path=db, force=True)["updated"] is True


def test_status_dormant_until_minimum(monkeypatch, tmp_path):
    db = str(tmp_path / "m.db")
    monkeypatch.setenv("APEX_MARKET_MEMORY_MIN_SESSIONS", "2")
    capture_snapshot(sample(), path=db, force=True)
    s = status(path=db)
    assert s["state"] == "DORMANT"
    assert s["learning_ready"] is False
    assert diagnostics(path=db)["storage"]["secrets_persisted"] is False


def test_routes_return_200(monkeypatch, tmp_path):
    monkeypatch.setenv("APEX_MARKET_MEMORY_DB", str(tmp_path / "m.db"))
    from flask import Flask
    from engine.market_memory_routes import register_market_memory_routes
    app = Flask(__name__)
    register_market_memory_routes(app, lambda: sample())
    client = app.test_client()
    for route in ("/api/market-memory/status", "/api/market-memory/diagnostics", "/api/market-memory/sessions", "/api/market-memory/similar"):
        assert client.get(route).status_code == 200
    assert client.post("/api/market-memory/capture").status_code == 200
