"""Canonical APEX institutional decision object used by APIs, dashboards, ledger and replay."""
from __future__ import annotations
from typing import Any, Dict, Mapping, Optional
import datetime as dt
from .institutional_narrative import build_institutional_narrative

VERSION = "66.3.2"
SCHEMA_VERSION = "apex.institutional_decision.v3"

def _d(value: Any) -> Dict[str, Any]: return dict(value) if isinstance(value, Mapping) else {}
def _l(value: Any): return list(value) if isinstance(value,(list,tuple)) else []


def _session_date(last: Mapping[str,Any], narrative: Mapping[str,Any]) -> str:
    for value in (last.get('session_date'), _d(last.get('market_state')).get('session_date'), last.get('target_session_date')):
        if value:
            return str(value)[:10]
    raw=narrative.get('generated_at')
    try:
        parsed=dt.datetime.fromisoformat(str(raw).replace('Z','+00:00'))
        if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=dt.timezone.utc)
        from zoneinfo import ZoneInfo
        return parsed.astimezone(ZoneInfo('America/New_York')).date().isoformat()
    except Exception:
        return dt.datetime.now(dt.timezone.utc).date().isoformat()

def _apply_thesis_lifecycle(last: Mapping[str,Any], narrative: Mapping[str,Any], candidate: Mapping[str,Any], ticker: str) -> Dict[str,Any]:
    try:
        from .thesis_lifecycle import persist_thesis
        nmarket=_d(narrative.get('market_state'))
        price=nmarket.get('price')
        persisted=persist_thesis(candidate,ticker=ticker,session_date=_session_date(last,narrative),price=price,market_closed=bool(_d(narrative.get('data_quality')).get('closed')),generated_at=narrative.get('generated_at'))
        # Preserve candidate-only descriptive fields while applying governed persisted state.
        out=dict(candidate)
        for key in ('thesis_id','session_date','state','dominant_direction','current_thesis','alternative_thesis','market_regime','raw_conviction','calibrated_conviction','effective_consensus','hard_invalidation','soft_invalidation','supporting_engines','contradicting_engines','abstaining_engines','known_unknowns','provenance','snapshot_hash','created_at','updated_at','invalidated_at','closed_at','revision','events','lifecycle'):
            if key in persisted: out[key]=persisted[key]
        out['schema_version']='apex.institutional_thesis.v2'
        return out
    except Exception as exc:
        out=dict(candidate)
        out['schema_version']='apex.institutional_thesis.v2'
        out['lifecycle']={'schema_version':'apex.thesis_lifecycle.v1','version':VERSION,'persisted':False,'state':out.get('state'),'transition_reason':'PERSISTENCE_UNAVAILABLE','error':str(exc)}
        return out

def _confidence_attribution(last: Mapping[str,Any], narrative: Mapping[str,Any]) -> Dict[str,Any]:
    consensus=_d(narrative.get('consensus')); sources=consensus.get('sources') or []
    dominant=consensus.get('dominant_direction','NEUTRAL'); rows=[]
    effective_by_engine={}
    for cluster in (consensus.get('clusters') or {}).values():
        for member in cluster.get('members') or []:
            effective_by_engine[str(member.get('engine'))]=float(member.get('effective_weight') or 0.0)
    for source in sources:
        name=source.get('engine_name') or source.get('source') or 'UNKNOWN'
        direction=source.get('direction','NEUTRAL')
        weight=effective_by_engine.get(str(name), float(source.get('reliability') or source.get('effective_weight') or 0.0))
        contribution=round(weight*(1 if direction==dominant and dominant!='NEUTRAL' else -1 if direction in {'BULLISH','BEARISH'} and direction!=dominant else 0),4)
        rows.append({'engine':name,'direction':direction,'contribution':contribution,'reliability':source.get('reliability'),'freshness':source.get('freshness_state') or source.get('freshness'),'explanation':f"normalized {name} opinion"})
    total=round(sum(r['contribution'] for r in rows),4)
    return {'schema_version':'apex.confidence_attribution.v3','contributors':rows,'deterministic_total':total,'mathematically_consistent':abs(total-sum(r['contribution'] for r in rows))<1e-9,'historical_calibration_applied':False}

def build_canonical_institutional_decision(last_result: Mapping[str, Any], *, recommendation_id: Optional[str] = None,
                                           session_state: Optional[str] = None) -> Dict[str, Any]:
    last=_d(last_result); narrative=build_institutional_narrative(last,session_state=session_state); consensus=narrative['consensus']; conviction=narrative['conviction']; candidate_thesis=_d(narrative.get('thesis')); acceptance=_d(narrative.get('acceptance'))
    raw_market=_d(last.get('market_state')); market=dict(raw_market or _d(narrative.get('market_state'))); execution=_d(last.get('execution_intelligence') or last.get('execution_os')); position=_d(last.get('position_quality') or last.get('position_quality_snapshot')); recommendation=_d(last.get('recommendation') or last.get('premium_strategy')); provider=_d(last.get('provider_health')); ledger=_d(last.get('recommendation_ledger'))
    ticker=str(last.get('ticker') or market.get('ticker') or 'SPX').upper(); thesis=_apply_thesis_lifecycle(last,narrative,candidate_thesis,ticker)
    narrative=dict(narrative); narrative['thesis']=thesis; narrative['primary_thesis']=thesis.get('current_thesis',narrative.get('primary_thesis')); narrative['alternate_thesis']=thesis.get('alternative_thesis',narrative.get('alternate_thesis'))
    direction=consensus.get('dominant_direction',consensus.get('direction','UNKNOWN')); action=recommendation.get('action') or recommendation.get('state') or last.get('decision_state') or 'NO_TRADE'
    thesis_state=str(thesis.get('state') or 'UNKNOWN').upper(); actionable=bool(narrative['trade_guidance_enabled'] and thesis_state=='ACTIVE' and direction in {'BULLISH','BEARISH'} and conviction.get('score',0)>=55 and not conviction.get('blocking_conditions'))
    if not actionable: action='NO_TRADE'
    return {
      'schema_version':SCHEMA_VERSION,'engine_version':VERSION,'recommendation_id':recommendation_id,'timestamp':narrative['generated_at'],'generated_at':narrative['generated_at'],
      'ticker':ticker,'instrument':last.get('instrument') or ticker,'market_state':market,'strategy':recommendation.get('strategy') or recommendation.get('name'),'action':action,'decision_state':action,'direction':direction,'status':'ACTIONABLE' if actionable else 'MARKET_CLOSED' if narrative.get('data_quality',{}).get('closed') else 'THESIS_INVALIDATED' if thesis_state=='INVALIDATED' else 'THESIS_CONFLICTED' if thesis_state=='CONFLICTED' else 'THESIS_WEAKENING' if thesis_state=='WEAKENING' else 'THESIS_FORMING' if thesis_state=='FORMING' else 'FAIL_CLOSED','actionable':actionable,
      'authoritative_contract':True,'decision_authority':'institutional_decision_object','market_narrative':narrative,'narrative':narrative,'primary_thesis':narrative.get('primary_thesis'),'alternate_thesis':narrative.get('alternate_thesis'),'institutional_thesis':thesis,'thesis':thesis,'acceptance':acceptance,'engine_opinions':narrative.get('engine_opinions') or [],'institutional_consensus':consensus,'consensus':consensus,'raw_conviction':conviction.get('raw_conviction'),'calibrated_conviction':conviction.get('calibrated_conviction'),'calibration_state':conviction.get('calibration_state'),'conviction':conviction,'evidence_conflict_matrix':narrative.get('evidence_conflict_matrix') or [],'evidence_graph':narrative.get('evidence_graph') or {},'confidence_attribution':_confidence_attribution(last,narrative),
      'execution_score':execution.get('execution_score') or execution.get('score'),'execution_snapshot':execution,'position_quality':position.get('position_quality_score') or position.get('score'),'position_quality_snapshot':position,'liquidity_and_fill_conditions':{'liquidity_score':execution.get('liquidity_score'),'fill_probability':execution.get('fill_probability'),'fill_probability_label':'HEURISTIC_UNLESS_CALIBRATED','expected_slippage':execution.get('expected_slippage'),'estimated_time_to_fill':execution.get('estimated_time_to_fill')},
      'risks':narrative['risk_drivers'],'invalidation':narrative['invalidation_conditions'],'invalidations':narrative['invalidation_conditions'],'targets_and_decision_levels':_d(recommendation.get('levels') or last.get('decision_levels')),'institutional_checklist':_l(execution.get('checklist') or last.get('institutional_checklist')),
      'data_freshness':narrative.get('freshness'),'provider_health':provider,'evidence_and_provenance':{'evidence':_d(last.get('evidence')),'engine_opinions':narrative.get('engine_opinions') or [],'acceptance':acceptance,'conflict_matrix':narrative.get('evidence_conflict_matrix') or [],'reasoning_graph':narrative.get('evidence_graph') or {},'provenance':{'canonical_builder':'institutional_decision_object','builder_version':VERSION,'narrative':narrative.get('provenance')}},'recommendation_lifecycle':ledger.get('lifecycle') or recommendation.get('lifecycle'),'evolution_timeline':(ledger.get('events') or []) + (thesis.get('events') or []),'thesis_lifecycle':thesis.get('lifecycle') or {},'thesis_evolution_timeline':thesis.get('events') or [],'build_metadata':{'build_version':VERSION,'narrative_version':narrative.get('engine_version'),'schema_version':SCHEMA_VERSION},
      'fail_closed':not actionable,'historical_performance_claimed':False,
    }
