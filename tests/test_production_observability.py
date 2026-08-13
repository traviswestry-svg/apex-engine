import time
from flask import Flask
from engine.production_observability import integration_health, metrics_snapshot, reset_metrics, timed
from engine.production_routes import register_production_routes


def setup_function():
    reset_metrics()


def test_timed_records_bounded_latency_summary():
    with timed('decision_cycle'):
        time.sleep(.001)
    data = metrics_snapshot()['components']['decision_cycle']
    assert data['samples'] == 1
    assert data['p50_ms'] >= 0
    assert data['errors'] == 0


def test_timed_records_errors_without_swallowing():
    try:
        with timed('broken'):
            raise ValueError('bad feed')
    except ValueError:
        pass
    data = metrics_snapshot()['components']['broken']
    assert data['errors'] == 1
    assert data['last_error']['type'] == 'ValueError'


def test_integration_health_is_honest_about_missing_capabilities():
    h = integration_health(capabilities={'institutional_state': True, 'provenance': False})
    assert h['status'] == 'DEGRADED'
    assert h['ready'] is False
    assert h['missing_capabilities'] == ['provenance']


def test_production_routes_return_503_when_not_ready():
    app = Flask(__name__)
    register_production_routes(app, capability_provider=lambda: {'institutional_state': True, 'provenance': False})
    c = app.test_client()
    assert c.get('/api/system/metrics').status_code == 200
    r = c.get('/api/system/readiness')
    assert r.status_code == 503
    assert r.get_json()['readiness']['ready'] is False


def test_production_routes_return_200_when_ready():
    app = Flask(__name__)
    register_production_routes(app, capability_provider=lambda: {'institutional_state': True, 'provenance': True})
    r = app.test_client().get('/api/system/readiness')
    assert r.status_code == 200
    assert r.get_json()['readiness']['status'] == 'HEALTHY'
