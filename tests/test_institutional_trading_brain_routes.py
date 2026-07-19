from flask import Flask
from engine.institutional_trading_brain_routes import register_institutional_trading_brain_routes


def test_trading_brain_routes(monkeypatch, tmp_path):
    monkeypatch.setenv("APEX_MARKET_MEMORY_DB", str(tmp_path / "memory.db"))
    app = Flask(__name__)
    register_institutional_trading_brain_routes(app, lambda: {"ticker": "SPX", "data_fresh": True})
    client = app.test_client()
    for route in (
        "/api/trading-brain/status",
        "/api/trading-brain/diagnostics",
        "/api/trading-brain/thesis",
        "/api/trading-brain/evidence",
        "/api/trading-brain/calibration?before=2026-07-19T12:00:00%2B00:00",
    ):
        response = client.get(route)
        assert response.status_code == 200
        assert response.get_json()["ok"] is True
