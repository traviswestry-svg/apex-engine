"""Routes for APEX 20.1-20.3."""
from flask import jsonify,request
from .institutional_execution_optimizer_v201 import build_execution_plan
from .market_replay_learning_lab_v202 import build_replay_snapshot,replay_session
from .strategy_intelligence_v203 import build_strategy_intelligence

def register_institutional_decision_suite_routes(app,last_result_provider):
 def cur():
  v=last_result_provider() if callable(last_result_provider) else {}; return v if isinstance(v,dict) else {}
 @app.get('/api/execution-optimizer/status')
 def eo_status(): return jsonify(build_execution_plan(cur()))
 @app.get('/api/execution-optimizer/plan')
 def eo_plan(): return jsonify(build_execution_plan(cur()))
 @app.get('/api/replay-learning-lab/status')
 def rl_status():
  x=build_replay_snapshot(cur()); return jsonify({'ok':True,'version':'13.2.0_MARKET_REPLAY_LEARNING_LAB','snapshot':x,'read_only':True})
 @app.post('/api/replay-learning-lab/replay')
 def rl_replay():
  p=request.get_json(silent=True) or {}; return jsonify(replay_session(p.get('frames') or []))
 @app.get('/api/strategy-intelligence/status')
 def si_status(): return jsonify(build_strategy_intelligence(cur()))
 @app.get('/api/strategy-intelligence/diagnostics')
 def si_diag(): return jsonify(build_strategy_intelligence(cur()))
