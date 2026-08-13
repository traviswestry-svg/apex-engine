from flask import Flask
from engine.institutional_ai_trading_coach_routes import register_institutional_ai_trading_coach_routes


def client(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'coach_routes.db'))
    app=Flask(__name__)
    register_institutional_ai_trading_coach_routes(app,last_result_provider=lambda:{'ticker':'SPX','spx':6000})
    return app.test_client()


def test_coach_routes(tmp_path, monkeypatch):
    c=client(tmp_path,monkeypatch)
    for path in ['/api/trading-coach/status','/api/trading-coach/diagnostics','/api/trading-coach/scorecard']:
        assert c.get(path).status_code==200
    assert c.post('/api/trading-coach/pre-trade',json={'human_confirmed':False}).status_code==200
    assert c.post('/api/trading-coach/active-trade',json={'tp1_reached':True}).status_code==200
    assert c.post('/api/trading-coach/post-trade',json={'chased':True}).status_code==200
    assert c.post('/api/trading-coach/reviews',json={'phase':'POST_TRADE','trade_id':'R1'}).status_code==200
