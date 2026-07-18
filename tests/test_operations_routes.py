from flask import Flask
from engine.operations_routes import register_operations_routes


def build_app():
    app = Flask(__name__, template_folder="../templates")
    app.config["TESTING"] = True
    @app.get('/api/market_status')
    def market_status(): return {'ok': True}
    register_operations_routes(app)
    return app


def test_endpoint_inventory_includes_itself():
    app = build_app()
    r = app.test_client().get('/api/endpoints')
    assert r.status_code == 200
    routes = {x['route'] for x in r.get_json()['endpoints']}
    assert '/api/endpoints' in routes
    assert '/api/system/checks' in routes


def test_consolidated_checks_are_explicit_about_blocked_history():
    app = build_app()
    r = app.test_client().get('/api/system/checks')
    assert r.status_code == 200
    payload = r.get_json()
    assert payload['checks']['recommendation_ledger']['status'] == 'BLOCKED'
    assert payload['checks']['calibration']['status'] in {'BLOCKED', 'WARN'}


def test_named_check_and_unknown_check():
    app = build_app()
    assert app.test_client().get('/api/system/checks/application').status_code == 200
    assert app.test_client().get('/api/system/checks/not-real').status_code == 404


def test_operations_page_renders():
    app = build_app()
    r = app.test_client().get('/apex_os/operations')
    assert r.status_code == 200
    assert b'Operations Center' in r.data
