from flask import Flask
from engine.institutional_reasoning_v251_routes import register_institutional_reasoning_v251_routes, verify_registered


def test_routes_register_and_evaluate():
    app = Flask(__name__)
    register_institutional_reasoning_v251_routes(app, last_result_provider=lambda: {})
    assert verify_registered(app) == []
    client = app.test_client()
    assert client.get('/api/institutional-reasoning/status').status_code == 200
    assert client.get('/api/institutional-reasoning/current').status_code == 200
    assert client.get('/api/institutional-reasoning/evidence-ranking').status_code == 200
    assert client.post('/api/institutional-reasoning/evaluate', json={}).status_code == 200
    assert client.post('/api/institutional-reasoning/evaluate', data='bad', content_type='text/plain').status_code == 400
