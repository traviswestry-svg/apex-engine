"""APEX 20.2 Market Replay & Learning Lab."""
from __future__ import annotations
from datetime import datetime,timezone
from typing import Any,Dict,List
from .institutional_decision_engine_v20 import build_institutional_decision
from .institutional_execution_optimizer_v201 import build_execution_plan
VERSION='13.2.0_MARKET_REPLAY_LEARNING_LAB'

def build_replay_snapshot(last:Dict[str,Any])->Dict[str,Any]:
    decision=build_institutional_decision(last if isinstance(last,dict) else {})
    execution=build_execution_plan(last,decision)
    return {'captured_at':datetime.now(timezone.utc).isoformat(),'ticker':decision.get('ticker','SPX'),'market_timestamp':last.get('timestamp') or last.get('updated_at'),'decision':decision,'execution_plan':execution,'source_fresh':last.get('data_fresh') is not False}

def replay_session(frames:List[Dict[str,Any]])->Dict[str,Any]:
    safe=[x for x in frames if isinstance(x,dict)][:500]
    snapshots=[build_replay_snapshot(x) for x in safe]
    candidates=sum(1 for x in snapshots if x['decision'].get('decision')=='TRADE_CANDIDATE')
    changes=sum(1 for a,b in zip(snapshots,snapshots[1:]) if a['decision'].get('bias')!=b['decision'].get('bias'))
    return {'ok':True,'version':VERSION,'evaluated_at':datetime.now(timezone.utc).isoformat(),'frame_count':len(snapshots),'trade_candidate_frames':candidates,'bias_changes':changes,'snapshots':snapshots,'guardrails':{'historical_analysis_only':True,'broker_mutation':False,'look_ahead_prohibited':True,'outcomes_not_injected_into_prior_frames':True}}
