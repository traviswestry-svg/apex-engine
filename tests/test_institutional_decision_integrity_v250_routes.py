from flask import Flask
from engine.institutional_decision_integrity_v250_routes import (
    register_institutional_decision_integrity_v250_routes, verify_registered,
)


def test_routes_register_and_evaluate():
    app = Flask(__name__)
    register_institutional_decision_integrity_v250_routes(app, last_result_provider=lambda: {})
    assert verify_registered(app) == []
    client = app.test_client()
    assert client.get('/api/decision-integrity/status').status_code == 200
    assert client.get('/api/decision-integrity/current').status_code == 200
    assert client.get('/api/decision-integrity/evidence-health').status_code == 200
    assert client.post('/api/decision-integrity/evaluate', json={}).status_code == 200
    assert client.post('/api/decision-integrity/evaluate', data='bad').status_code == 400
