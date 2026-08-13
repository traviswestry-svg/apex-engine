from flask import Flask
from engine.institutional_intelligence_routes import register_institutional_intelligence_routes


def test_routes_fail_closed_and_exist(tmp_path, monkeypatch):
    monkeypatch.setenv('RECOMMENDATION_LEDGER_DB_PATH', str(tmp_path / 'ledger.db'))
    app = Flask(__name__, template_folder='../templates')
    register_institutional_intelligence_routes(app, last_result_provider=lambda: {})
    c = app.test_client()
    r = c.get('/api/institutional-decision')
    assert r.status_code == 200
    assert r.get_json()['fail_closed'] is True
    assert c.get('/api/decision-review/missing').status_code == 404
