from flask import Flask
from engine.continuous_learning_routes import register_continuous_learning_routes

def test_routes(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'routes.db'))
    app=Flask(__name__); register_continuous_learning_routes(app,last_result_provider=lambda:{'ticker':'SPX'})
    c=app.test_client()
    for path in ['/api/continuous-learning/status','/api/continuous-learning/diagnostics','/api/continuous-learning/calibration','/api/continuous-learning/performance','/api/continuous-learning/recommendations']:
        assert c.get(path).status_code==200
    assert c.post('/api/continuous-learning/outcomes',json={}).get_json()['status']=='REJECTED'
