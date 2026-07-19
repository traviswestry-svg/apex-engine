from flask import Flask
from engine.premium_discipline_routes import register_premium_discipline_routes

def test_new_routes(tmp_path):
    app=Flask(__name__)
    register_premium_discipline_routes(app,last_result_provider=lambda:{},db_path=str(tmp_path/'r.db'))
    c=app.test_client()
    assert c.get('/api/premium_discipline/learning').status_code==200
    assert c.post('/api/premium_discipline/learning/samples',json={'ticker':'SPX','strategy':'IRON_CONDOR','context':{'premium_regime':'GAMMA_PIN'},'outcome':'WIN','pnl':50}).status_code==200
    assert c.post('/api/premium_discipline/trade-lifecycle',json={'position':{'position_id':'p1','entry_credit':2,'current_debit':.5,'max_loss':800},'market':{'minutes_to_close':100}}).status_code==200
