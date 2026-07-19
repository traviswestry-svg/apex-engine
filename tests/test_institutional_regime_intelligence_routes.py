from flask import Flask
from engine.institutional_regime_intelligence_routes import register_institutional_regime_intelligence_routes


def test_regime_routes_return_200():
    app=Flask(__name__)
    register_institutional_regime_intelligence_routes(app,last_result_provider=lambda:{"ticker":"SPX"})
    client=app.test_client()
    for path in ("/api/regime-intelligence/status","/api/regime-intelligence/diagnostics","/api/regime-intelligence/scores","/api/regime-intelligence/transition","/api/regime-intelligence/guidance"):
        response=client.get(path)
        assert response.status_code == 200
        assert response.get_json()["ok"] is True
