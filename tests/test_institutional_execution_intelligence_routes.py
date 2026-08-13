from flask import Flask
from engine.institutional_execution_intelligence_routes import register_institutional_execution_intelligence_routes


def test_execution_intelligence_routes(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'routes.db'))
    app=Flask(__name__)
    register_institutional_execution_intelligence_routes(app,last_result_provider=lambda:{'ticker':'SPX','spx':6000})
    c=app.test_client()
    assert c.get('/api/execution-intelligence/status').status_code==200
    assert c.get('/api/execution-intelligence/diagnostics').status_code==200
    assert c.post('/api/execution-intelligence/score',json={'entry_price':6000,'stop_price':5995}).status_code==200
    created=c.post('/api/execution-intelligence/lifecycles',json={'entry_price':6000,'stop_price':5995}).get_json()
    lid=created['lifecycle_id']
    assert c.post(f'/api/execution-intelligence/lifecycles/{lid}/transition',json={'to_state':'APPROVED'}).status_code==200
    assert c.get(f'/api/execution-intelligence/lifecycles/{lid}/replay').status_code==200
    assert c.get('/api/execution-intelligence/journal').status_code==200
