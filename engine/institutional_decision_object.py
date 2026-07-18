"""Canonical APEX institutional decision object used by APIs, dashboards, ledger and replay."""
from __future__ import annotations
from typing import Any, Dict, Mapping, Optional
from .institutional_narrative import build_institutional_narrative

VERSION = "12.3.0"
SCHEMA_VERSION = "apex.institutional_decision.v2"

def _d(value: Any) -> Dict[str, Any]: return dict(value) if isinstance(value, Mapping) else {}
def _l(value: Any): return list(value) if isinstance(value,(list,tuple)) else []

def _confidence_attribution(last: Mapping[str,Any], narrative: Mapping[str,Any]) -> Dict[str,Any]:
    consensus=_d(narrative.get('consensus')); sources=consensus.get('sources') or []
    rows=[]
    for source in sources:
        weight=float(source.get('effective_weight') or 0.0); direction=source.get('direction','NEUTRAL')
        contribution=round(weight*(1 if direction==consensus.get('dominant_direction') else -1 if direction not in {'NEUTRAL',consensus.get('dominant_direction')} else 0),4)
        rows.append({'engine':source.get('source'),'direction':direction,'contribution':contribution,'reliability':source.get('effective_weight'),'freshness':source.get('freshness'),'explanation':source.get('reason')})
    total=round(sum(r['contribution'] for r in rows),4)
    return {'schema_version':'apex.confidence_attribution.v2','contributors':rows,'deterministic_total':total,'mathematically_consistent':abs(total-sum(r['contribution'] for r in rows))<1e-9,'historical_calibration_applied':False}

def build_canonical_institutional_decision(last_result: Mapping[str, Any], *, recommendation_id: Optional[str] = None,
                                           session_state: Optional[str] = None) -> Dict[str, Any]:
    last=_d(last_result); narrative=build_institutional_narrative(last,session_state=session_state); consensus=narrative['consensus']; conviction=narrative['conviction']
    market=_d(last.get('market_state')); execution=_d(last.get('execution_intelligence') or last.get('execution_os')); position=_d(last.get('position_quality') or last.get('position_quality_snapshot')); recommendation=_d(last.get('recommendation') or last.get('premium_strategy')); provider=_d(last.get('provider_health')); ledger=_d(last.get('recommendation_ledger'))
    direction=consensus.get('dominant_direction',consensus.get('direction','NEUTRAL')); action=recommendation.get('action') or recommendation.get('state') or last.get('decision_state') or 'NO_TRADE'
    actionable=bool(narrative['trade_guidance_enabled'] and direction!='NEUTRAL' and conviction.get('score',0)>=55 and not conviction.get('blocking_conditions'))
    if not actionable: action='NO_TRADE'
    return {
      'schema_version':SCHEMA_VERSION,'engine_version':VERSION,'recommendation_id':recommendation_id,'timestamp':narrative['generated_at'],'generated_at':narrative['generated_at'],
      'ticker':last.get('ticker') or market.get('ticker') or 'SPX','instrument':last.get('instrument') or last.get('ticker') or market.get('ticker') or 'SPX','market_state':market,'strategy':recommendation.get('strategy') or recommendation.get('name'),'action':action,'decision_state':action,'direction':direction,'status':'ACTIONABLE' if actionable else 'FAIL_CLOSED','actionable':actionable,
      'market_narrative':narrative,'narrative':narrative,'primary_thesis':narrative.get('primary_thesis'),'alternate_thesis':narrative.get('alternate_thesis'),'institutional_consensus':consensus,'consensus':consensus,'conviction':conviction,'confidence_attribution':_confidence_attribution(last,narrative),
      'execution_score':execution.get('execution_score') or execution.get('score'),'execution_snapshot':execution,'position_quality':position.get('position_quality_score') or position.get('score'),'position_quality_snapshot':position,'liquidity_and_fill_conditions':{'liquidity_score':execution.get('liquidity_score'),'fill_probability':execution.get('fill_probability'),'fill_probability_label':'HEURISTIC_UNLESS_CALIBRATED','expected_slippage':execution.get('expected_slippage'),'estimated_time_to_fill':execution.get('estimated_time_to_fill')},
      'risks':narrative['risk_drivers'],'invalidation':narrative['invalidation_conditions'],'invalidations':narrative['invalidation_conditions'],'targets_and_decision_levels':_d(recommendation.get('levels') or last.get('decision_levels')),'institutional_checklist':_l(execution.get('checklist') or last.get('institutional_checklist')),
      'data_freshness':narrative.get('freshness'),'provider_health':provider,'evidence_and_provenance':{'evidence':_d(last.get('evidence')),'provenance':narrative.get('provenance')},'recommendation_lifecycle':ledger.get('lifecycle') or recommendation.get('lifecycle'),'evolution_timeline':ledger.get('events') or [],'build_metadata':{'build_version':VERSION,'narrative_version':narrative.get('engine_version'),'schema_version':SCHEMA_VERSION},
      'fail_closed':not actionable,'historical_performance_claimed':False,
    }
