"""Routes for APEX 20.1-20.3."""
from datetime import datetime, timezone
from typing import Any, Dict, List

from flask import jsonify,request
from .institutional_execution_optimizer_v201 import build_execution_plan
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


# ── Market Replay & Learning Lab (absorbed from market_replay_learning_lab_v202.py,
#    Sprint 4). Sole consumer was this routes module. Payload version unchanged.
from .institutional_decision_engine import build_institutional_decision
REPLAY_LAB_VERSION='13.2.0_MARKET_REPLAY_LEARNING_LAB'


def build_replay_snapshot(last:Dict[str,Any])->Dict[str,Any]:
    decision=build_institutional_decision(last if isinstance(last,dict) else {})
    execution=build_execution_plan(last,decision)
    return {'captured_at':datetime.now(timezone.utc).isoformat(),'ticker':decision.get('ticker','SPX'),'market_timestamp':last.get('timestamp') or last.get('updated_at'),'decision':decision,'execution_plan':execution,'source_fresh':last.get('data_fresh') is not False}

def replay_session(frames:List[Dict[str,Any]])->Dict[str,Any]:
    safe=[x for x in frames if isinstance(x,dict)][:500]
    snapshots=[build_replay_snapshot(x) for x in safe]
    candidates=sum(1 for x in snapshots if x['decision'].get('decision')=='TRADE_CANDIDATE')
    changes=sum(1 for a,b in zip(snapshots,snapshots[1:]) if a['decision'].get('bias')!=b['decision'].get('bias'))
    return {'ok':True,'version':REPLAY_LAB_VERSION,'evaluated_at':datetime.now(timezone.utc).isoformat(),'frame_count':len(snapshots),'trade_candidate_frames':candidates,'bias_changes':changes,'snapshots':snapshots,'guardrails':{'historical_analysis_only':True,'broker_mutation':False,'look_ahead_prohibited':True,'outcomes_not_injected_into_prior_frames':True}}

