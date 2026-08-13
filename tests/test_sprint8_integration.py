from flask import Flask
from engine.institutional_state_routes import register_institutional_state_routes
from engine.production_observability import metrics_snapshot, reset_metrics


def test_institutional_state_request_is_observed():
    reset_metrics()
    app = Flask(__name__)
    register_institutional_state_routes(app, last_result_provider=lambda: {'decision_state': 'HOLD', 'confidence': 72})
    response = app.test_client().get('/api/institutional_state?ticker=SPX')
    assert response.status_code == 200
    metrics = metrics_snapshot()
    assert metrics['counters']['institutional_state.requests'] == 1
    assert metrics['components']['institutional_state.build']['samples'] == 1
