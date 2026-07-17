from flask import Flask

from engine.institutional_state_routes import register_institutional_state_routes


def test_routes_expose_state_graph_trace_and_story():
    app = Flask(__name__)
    current = {
        "decision_state": "NO_TRADE",
        "institutional_intelligence": {"institutional_bias": "NEUTRAL", "decision_recommendation": "NO TRADE"},
    }
    register_institutional_state_routes(app, last_result_provider=lambda: current)
    client = app.test_client()
    for path, key in [
        ("/api/institutional_state", "institutional_state"),
        ("/api/evidence_graph", "evidence_graph"),
        ("/api/decision_trace", "decision_trace"),
        ("/api/market_story", "market_story"),
    ]:
        response = client.get(path + "?ticker=SPX")
        assert response.status_code == 200
        body = response.get_json()
        assert body["ok"] is True
        assert key in body


def test_dashboard_files_expose_institutional_view():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates" / "apex_os.html").read_text(encoding="utf-8")
    js = (root / "static" / "js" / "apex_os.js").read_text(encoding="utf-8")
    assert 'id="institutionalViewCard"' in template
    assert 'id="institutionalGraph"' in template
    assert "/api/institutional_state" in js
    assert "no fabricated intent" in template.lower()
