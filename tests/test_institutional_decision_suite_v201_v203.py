from flask import Flask
from engine.institutional_execution_optimizer_v201 import build_execution_plan
from engine.market_replay_learning_lab_v202 import build_replay_snapshot,replay_session
from engine.strategy_intelligence_v203 import build_strategy_intelligence
from engine.institutional_decision_suite_routes import register_institutional_decision_suite_routes

def sample():
 return {'ticker':'SPX','price':6000,'atr':12,'data_fresh':True,'dealer_positioning':{'net_gex':-1,'call_wall':6030,'put_wall':5970},'options_flow':{'calls':1000000,'puts':200000},'volume_profile':{'poc':5998,'vah':6005,'val':5990},'probability':{'bullish':70}}

def test_execution_optimizer_is_advisory():
 x=build_execution_plan(sample()); assert x['guardrails']['broker_mutation'] is False; assert x['sizing']['max_contracts']==0

def test_strategy_defined_risk():
 x=build_strategy_intelligence(sample()); assert x['construction_rules']['defined_risk_only']; assert x['guardrails']['automatic_execution'] is False

def test_replay_preserves_order_and_blocks_lookahead():
 x=replay_session([sample(),dict(sample(),price=6002)]); assert x['frame_count']==2; assert x['guardrails']['look_ahead_prohibited']

def test_snapshot_contains_decision_and_plan():
 x=build_replay_snapshot(sample()); assert 'decision' in x and 'execution_plan' in x

def test_routes_http_200():
 app=Flask(__name__); register_institutional_decision_suite_routes(app,sample); c=app.test_client()
 for path in ['/api/execution-optimizer/status','/api/execution-optimizer/plan','/api/replay-learning-lab/status','/api/strategy-intelligence/status','/api/strategy-intelligence/diagnostics']:
  assert c.get(path).status_code==200
 assert c.post('/api/replay-learning-lab/replay',json={'frames':[sample()]}).status_code==200
