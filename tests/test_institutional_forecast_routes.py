from flask import Flask
from engine.institutional_forecast_routes import register_institutional_forecast_routes


def test_forecast_routes_return_200():
    app=Flask(__name__)
    register_institutional_forecast_routes(app,last_result_provider=lambda:{"ticker":"SPX","price":6300,"expected_move":40})
    client=app.test_client()
    for path in ("/api/institutional-forecast/status","/api/institutional-forecast/diagnostics","/api/institutional-forecast/paths","/api/institutional-forecast/bands","/api/institutional-forecast/timing"):
        response=client.get(path)
        assert response.status_code==200
        assert response.get_json()["ok"] is True
