"""APEX 21.2 — Institutional Trading Workspace aggregation."""
from datetime import datetime, timezone
from typing import Any, Dict
from .institutional_decision_engine_v20 import build_institutional_decision
from .institutional_execution_optimizer_v201 import build_execution_plan
from .strategy_intelligence_v203 import build_strategy_intelligence
from .institutional_volume_profile_v211 import build_volume_profile_intelligence
VERSION="14.2.0_INSTITUTIONAL_TRADING_WORKSPACE"

def build_workspace(last: Dict[str,Any])->Dict[str,Any]:
    last=last if isinstance(last,dict) else {}
    decision=build_institutional_decision(last)
    execution=build_execution_plan(last,decision)
    strategy=build_strategy_intelligence(last,decision)
    volume=build_volume_profile_intelligence(last)
    confidence=float(decision.get('confidence') or 0)
    coverage=float(decision.get('evidence_coverage') or 0)
    data_quality=100 if volume.get('state')=='READY' else 65
    safety=100 if not decision.get('execution_eligible') else 90
    readiness=round(max(0,min(100,confidence*.55+coverage*.25+data_quality*.1+safety*.1)),1)
    grade='A+' if readiness>=90 else 'A' if readiness>=80 else 'B' if readiness>=70 else 'WATCH' if readiness>=60 else 'STAND_DOWN'
    return {'ok':True,'version':VERSION,'evaluated_at':datetime.now(timezone.utc).isoformat(),'ticker':decision.get('ticker','SPX'),
      'decision_banner':{'decision':decision.get('decision'),'bias':decision.get('bias'),'confidence':confidence,'regime':decision.get('regime'),'headline':decision.get('headline'),'preferred_strategy':strategy.get('preferred_structure'),'grade':grade},
      'execution_readiness':{'score':readiness,'grade':grade,'eligible':bool(decision.get('execution_eligible')),'human_confirmation_required':True},
      'workspace':{'decision':decision,'execution_plan':execution,'strategy':strategy,'volume_profile':volume,
        'layout':{'top':['decision_banner','dealer_positioning','market_structure','probability'],'center':['primary_chart','volume_profile_overlay','execution_levels'],'right':['trade_plan','entry','stop','tp1','tp2','tp3','position_size'],'bottom':['flow_tape','news','gamma','story','replay']}},
      'context_layout':_context(last),'guardrails':{'read_only':True,'broker_mutation':False,'automatic_execution':False,'kill_switch_authoritative':True}}

def _context(last):
    session=str(last.get('session') or last.get('market_session') or 'UNKNOWN').upper()
    if 'PRE' in session:return {'mode':'PREMARKET','focus':['overnight_inventory','expected_move','dealer_positioning']}
    if session in ('MARKET_OPEN','OPEN','RTH'):return {'mode':'EXECUTION','focus':['decision','chart','volume_profile','trade_plan']}
    if 'AFTER' in session or 'CLOSED' in session:return {'mode':'REVIEW','focus':['replay','learning','session_review']}
    return {'mode':'BALANCED','focus':['market_structure','flow','risk']}
