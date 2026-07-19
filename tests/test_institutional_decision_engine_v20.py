import json
from flask import Flask
from engine.institutional_decision_engine_v20 import build_institutional_decision, VERSION
from engine.institutional_decision_engine_routes import register_institutional_decision_engine_routes

def sample():
    return {'ticker':'SPX','data_fresh':True,'market_state':{'price':6000,'previous_day_high':6010,'previous_day_low':5975,'overnight_high':6005,'overnight_low':5985,'session_high':6004,'session_low':5990,'atr':22,'trend':'UP'},'dealer_positioning':{'gamma_flip':5995,'call_wall':6020,'put_wall':5960,'net_gex':-100,'dealer_delta':50,'vanna':10,'charm':5},'flow_tape':[{'side':'CALL','type':'SWEEP','premium':400000,'opening':True,'repeat_count':4,'at_ask':True}], 'recommendation_history':[{'outcome':'WIN','setup':'ORB','regime':'TREND','hour':'10'} for _ in range(35)]}

def test_fuses_existing_engines_and_is_read_only():
    out=build_institutional_decision(sample()); assert out['version']==VERSION; assert out['bias']=='BULLISH'; assert len(out['evidence'])==5; assert out['guardrails']['broker_mutation'] is False; assert out['guardrails']['human_confirmation_required']

def test_stale_data_fails_closed():
    x=sample(); x['data_fresh']=False; out=build_institutional_decision(x); assert not out['execution_eligible']; assert 'STALE_DATA' in out['blocking_reasons']

def test_empty_state_stands_down():
    out=build_institutional_decision({}); assert out['decision']=='STAND_DOWN'; assert not out['execution_eligible']

def test_conflict_is_explicit():
    x=sample(); x['dealer_positioning']['dealer_delta']=-100; x['dealer_positioning']['vanna']=-20; x['dealer_positioning']['charm']=-20
    out=build_institutional_decision(x); assert isinstance(out['conflicting_sources'],list); assert 0<=out['confidence']<=100

def test_strategy_is_advisory_only():
    out=build_institutional_decision(sample()); assert out['strategy']['advisory_only']; assert out['strategy']['requires_option_chain_validation']

def test_no_secret_leak():
    x=sample(); x['POLYGON_API_KEY']='secret-123'; x['dealer_positioning']['consumer_secret']='secret-456'; raw=json.dumps(build_institutional_decision(x)); assert 'secret-123' not in raw and 'secret-456' not in raw

def test_routes_return_200():
    app=Flask(__name__); register_institutional_decision_engine_routes(app, sample); c=app.test_client()
    for path in ('/api/institutional-decision/status','/api/institutional-decision/diagnostics','/api/institutional-decision/scenarios','/api/institutional-decision/evidence','/api/institutional-decision/strategy'):
        assert c.get(path).status_code==200
