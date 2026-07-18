from flask import Flask
from engine.release_routes import register_release_routes


def test_release_routes_are_registered_and_non_mutating():
    app = Flask(__name__)
    register_release_routes(app)
    client = app.test_client()
    for path in (
        '/api/system/version', '/api/system/build', '/api/system/features',
        '/api/system/migrations', '/api/system/release',
    ):
        response = client.get(path)
        assert response.status_code in (200, 503)
        assert response.get_json()['ok'] is True
    assert client.post('/api/system/release').status_code == 405


def test_integrity_endpoint_reports_store_state():
    """The point of 11.0A: an empty store must report EMPTY, not a confident zero."""
    app = Flask(__name__)
    register_release_routes(app)
    client = app.test_client()
    r = client.get('/api/system/integrity')
    assert r.status_code in (200, 503)
    body = r.get_json()
    assert body['ok'] is True
    assert 'statistics_supportable' in body
    assert 'tables' in body


def test_endpoints_are_get_only():
    app = Flask(__name__)
    register_release_routes(app)
    client = app.test_client()
    for path in ('/api/system/version', '/api/system/build', '/api/system/features',
                 '/api/system/migrations', '/api/system/integrity', '/api/system/release'):
        assert client.post(path).status_code == 405, f"{path} must reject POST"


def test_backward_compatible_registration_name():
    """app.py imports register_release_manager_routes — it must keep working."""
    from engine.release_routes import register_release_manager_routes
    app = Flask(__name__)
    register_release_manager_routes(app)
    assert app.test_client().get('/api/system/version').status_code == 200
