"""APEX 21.2 — Institutional Trading Workspace aggregation."""
from datetime import datetime, timezone
from typing import Any, Dict
from .institutional_decision_engine import build_institutional_decision
from .institutional_execution_optimizer_v201 import build_execution_plan
from .strategy_intelligence_v203 import build_strategy_intelligence
from .institutional_volume_profile_v211 import build_volume_profile_intelligence
VERSION="14.2.0_INSTITUTIONAL_TRADING_WORKSPACE"

def build_workspace(last: Dict[str,Any])->Dict[str,Any]:
    last=last if isinstance(last,dict) else {}
    decision=build_institutional_decision(last)
    canonical=last.get('institutional_decision_object') if isinstance(last.get('institutional_decision_object'),dict) else {}
    if canonical.get('authoritative_contract'):
        conviction=canonical.get('conviction') if isinstance(canonical.get('conviction'),dict) else {}
        canonical_confidence=(canonical.get('calibrated_conviction') if canonical.get('calibrated_conviction') is not None
                              else canonical.get('raw_conviction'))
        if canonical_confidence is None: canonical_confidence=conviction.get('score') or conviction.get('raw_conviction')
        canonical_direction=str(canonical.get('direction') or 'NEUTRAL').upper()
        canonical_actionable=bool(canonical.get('actionable'))
        decision.update({
          'bias':canonical_direction,
          'confidence':float(canonical_confidence or 0),
          'execution_eligible':canonical_actionable,
          'decision':'TRADE_CANDIDATE' if canonical_actionable else 'WATCH' if canonical_direction in ('BULLISH','BEARISH') else 'STAND_DOWN',
          'headline':f"{canonical_direction} — canonical institutional decision",
          'evaluated_at':canonical.get('timestamp') or canonical.get('generated_at'),
          'authoritative_decision_source':'institutional_decision_object',
        })
    execution=build_execution_plan(last,decision)
    strategy=build_strategy_intelligence(last,decision)
    volume=build_volume_profile_intelligence(last)
    raw_confidence=float(decision.get('confidence') or 0)
    session=_session(last)
    runtime_state=str(last.get('status') or last.get('engine_mode') or '').upper()
    degraded=bool(last.get('stale') or last.get('partial') or last.get('timed_out_components') or 'DEGRADED' in runtime_state)
    breadth=last.get('breadth_regime') if isinstance(last.get('breadth_regime'),dict) else {}
    breadth_limited=not breadth or str(breadth.get('state') or 'DATA_LIMITED').upper()=='DATA_LIMITED'
    confidence_cap=95.0; cap_reasons=[]
    if session not in ('MARKET_OPEN','OPEN','RTH'): confidence_cap=min(confidence_cap,60.0); cap_reasons.append('SESSION_NOT_TRADEABLE')
    if degraded: confidence_cap=min(confidence_cap,55.0); cap_reasons.append('RUNTIME_DEGRADED')
    if breadth_limited: confidence_cap=min(confidence_cap,65.0); cap_reasons.append('BREADTH_DATA_LIMITED')
    confidence=min(raw_confidence,confidence_cap)
    if cap_reasons:
        decision['execution_eligible']=False
        execution=build_execution_plan(last,decision)
        strategy=build_strategy_intelligence(last,decision)
    coverage=float(decision.get('evidence_coverage') or 0)
    data_quality=100 if volume.get('state')=='READY' else 65
    safety=100 if not decision.get('execution_eligible') else 90
    readiness=round(max(0,min(100,confidence*.55+coverage*.25+data_quality*.1+safety*.1)),1)
    grade='A+' if readiness>=90 else 'A' if readiness>=80 else 'B' if readiness>=70 else 'WATCH' if readiness>=60 else 'STAND_DOWN'
    return {'ok':True,'version':VERSION,'evaluated_at':datetime.now(timezone.utc).isoformat(),'ticker':decision.get('ticker','SPX'),
      'decision_banner':{'decision':decision.get('decision'),'bias':decision.get('bias'),'confidence':confidence,'raw_confidence':raw_confidence,'confidence_cap':confidence_cap,'confidence_cap_reasons':cap_reasons,'regime':decision.get('regime'),'headline':decision.get('headline'),'preferred_strategy':strategy.get('preferred_structure'),'grade':grade,'authoritative_as_of':decision.get('evaluated_at')},
      'execution_readiness':{'score':readiness,'grade':grade,'eligible':bool(decision.get('execution_eligible')),'human_confirmation_required':True},
      'workspace':{'decision':decision,'execution_plan':execution,'strategy':strategy,'volume_profile':volume,
        'layout':{'top':['decision_banner','dealer_positioning','market_structure','probability'],'center':['primary_chart','volume_profile_overlay','execution_levels'],'right':['trade_plan','entry','stop','tp1','tp2','tp3','position_size'],'bottom':['flow_tape','news','gamma','story','replay']}},
      'context_layout':_context(last),'coherence':{'single_snapshot_contract':True,'session_state':session,'runtime_degraded':degraded,'breadth_limited':breadth_limited,'confidence_governed':confidence!=raw_confidence},'guardrails':{'read_only':True,'broker_mutation':False,'automatic_execution':False,'kill_switch_authoritative':True}}

def _session(last):
    session=last.get('session')
    if isinstance(session,dict): session=session.get('session_state') or session.get('session')
    return str(last.get('session_state') or (last.get('market_state') or {}).get('session_state') or session or 'UNKNOWN').upper()

def _context(last):
    session=_session(last)
    if 'PRE' in session:return {'mode':'PREMARKET','focus':['overnight_inventory','expected_move','dealer_positioning']}
    if session in ('MARKET_OPEN','OPEN','RTH'):return {'mode':'EXECUTION','focus':['decision','chart','volume_profile','trade_plan']}
    if 'AFTER' in session or 'CLOSED' in session:return {'mode':'REVIEW','focus':['replay','learning','session_review']}
    return {'mode':'BALANCED','focus':['market_structure','flow','risk']}
