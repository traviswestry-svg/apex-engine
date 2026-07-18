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
