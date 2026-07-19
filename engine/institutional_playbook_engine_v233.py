"""APEX 23.3 Institutional Playbook Engine — read-only playbook ranking."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional
from .institutional_forecast_engine_v232 import build_institutional_forecast
from .institutional_regime_intelligence_v231 import build_regime_intelligence
from .institutional_trading_brain_v230 import build_institutional_trading_brain

VERSION='16.3.0_INSTITUTIONAL_PLAYBOOK_ENGINE'; SEMANTIC_VERSION='16.3.0'; SCHEMA_VERSION='apex.institutional_playbook_engine.v1'

PLAYBOOKS={
'TREND_PULLBACK_CALL':('BULL_PATH',{'TREND_EXPANSION','VOLATILITY_EXPANSION'},'CALL_DEBIT_SPREAD'),
'TREND_PULLBACK_PUT':('BEAR_PATH',{'TREND_EXPANSION','VOLATILITY_EXPANSION'},'PUT_DEBIT_SPREAD'),
'BREAKOUT_RETEST_CALL':('BULL_PATH',{'TREND_EXPANSION','COMPRESSION'},'CALL_DEBIT_SPREAD'),
'BREAKDOWN_RETEST_PUT':('BEAR_PATH',{'TREND_EXPANSION','COMPRESSION'},'PUT_DEBIT_SPREAD'),
'VALUE_EDGE_FADE':('BALANCE_PATH',{'BALANCED_ROTATION','MEAN_REVERSION'},'DEFINED_RISK_CREDIT_SPREAD'),
'IRON_CONDOR_BALANCE':('BALANCE_PATH',{'BALANCED_ROTATION','COMPRESSION'},'IRON_CONDOR'),
'WAIT_FOR_CONFIRMATION':('BALANCE_PATH',{'TRANSITION'},'NO_TRADE'),
}

def _score(name:str, scenario:str, regimes:set, forecast:Mapping[str,Any], regime:Mapping[str,Any], brain:Mapping[str,Any])->Dict[str,Any]:
    probs=forecast.get('scenario_probabilities') or {}; primary_regime=str(regime.get('primary_regime') or 'TRANSITION')
    score=float(probs.get(scenario,0))*0.55
    reasons=[]
    if primary_regime in regimes: score+=22; reasons.append(f'Regime fit: {primary_regime}')
    if scenario==forecast.get('primary_scenario'): score+=12; reasons.append('Matches primary forecast')
    if brain.get('execution_readiness',{}).get('eligible'): score+=6; reasons.append('Trading Brain execution-ready')
    transition=str((regime.get('transition') or {}).get('state') or 'UNCONFIRMED')
    if transition in ('UNCONFIRMED','EMERGING') and name!='WAIT_FOR_CONFIRMATION': score-=18; reasons.append('Penalized for unconfirmed regime transition')
    if forecast.get('status')!='ACTIVE': score-=15; reasons.append('Forecast data is limited')
    score=round(max(0,min(100,score)),1)
    return {'playbook_id':name,'score':score,'scenario':scenario,'regime_fit':primary_regime in regimes,'reasons':reasons}

def build_institutional_playbooks(last:Dict[str,Any], history:Any=None, *, before:Optional[str]=None)->Dict[str,Any]:
    last=last if isinstance(last,dict) else {}
    forecast=build_institutional_forecast(last,history,before=before); regime=build_regime_intelligence(last,history,before=before); brain=build_institutional_trading_brain(last,history,before=before)
    ranked=[]
    for name,(scenario,regimes,strategy) in PLAYBOOKS.items():
        row=_score(name,scenario,regimes,forecast,regime,brain); row['strategy_family']=strategy
        row['entry_structure']={'trigger':'CONFIRM_SCENARIO_AND_STRUCTURE','location':'VALUE_EDGE_OR_RETEST','anti_chase':True}
        row['invalidation']={'condition':'SCENARIO_INVALIDATION_OR_STRUCTURE_FAILURE','source':'INSTITUTIONAL_FORECAST'}
        row['risk_controls']={'defined_risk_required':True,'human_confirmation_required':True,'max_hold_minutes':5 if strategy!='NO_TRADE' else 0}
        ranked.append(row)
    ranked.sort(key=lambda x:x['score'],reverse=True)
    selected=ranked[0]
    eligible=bool(brain.get('execution_readiness',{}).get('eligible')) and forecast.get('status')=='ACTIVE' and selected['strategy_family']!='NO_TRADE' and selected['score']>=55
    if not eligible and ranked[0]['playbook_id']!='WAIT_FOR_CONFIRMATION':
        wait=next(x for x in ranked if x['playbook_id']=='WAIT_FOR_CONFIRMATION'); wait['score']=max(wait['score'],55.0); ranked.sort(key=lambda x:x['score'],reverse=True); selected=ranked[0]
    return {'ok':True,'version':VERSION,'semantic_version':SEMANTIC_VERSION,'schema_version':SCHEMA_VERSION,'evaluated_at':datetime.now(timezone.utc).isoformat(),'ticker':last.get('ticker','SPX'),'status':'ACTIVE' if forecast.get('status')=='ACTIVE' else 'LIMITED','selected_playbook':selected,'ranked_playbooks':ranked,'execution_readiness':{'eligible':eligible,'state':'READY' if eligible else 'STAND_DOWN','blocking_reasons':[] if eligible else ['FORECAST_OR_BRAIN_NOT_EXECUTION_READY']},'context':{'primary_regime':regime.get('primary_regime'),'transition':regime.get('transition'),'primary_scenario':forecast.get('primary_scenario'),'scenario_probabilities':forecast.get('scenario_probabilities'),'brain_bias':brain.get('bias')},'guardrails':{'read_only':True,'broker_mutation':False,'automatic_execution':False,'automatic_strategy_selection':False,'human_confirmation_required':True,'existing_kill_switch_authoritative':True,'look_ahead_protected':bool(before)}}
