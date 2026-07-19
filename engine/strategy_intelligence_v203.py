"""APEX 20.3 Strategy Intelligence — advisory options-structure selection."""
from __future__ import annotations
from datetime import datetime,timezone
from typing import Any,Dict
from .institutional_decision_engine_v20 import build_institutional_decision
VERSION='13.3.0_STRATEGY_INTELLIGENCE'

def _f(v,d=0.0):
    try:return float(v)
    except:return d

def build_strategy_intelligence(last:Dict[str,Any],decision:Dict[str,Any]|None=None)->Dict[str,Any]:
    last=last if isinstance(last,dict) else {}; decision=decision or build_institutional_decision(last)
    bias=decision.get('bias','NEUTRAL'); regime=decision.get('regime','BALANCE'); conf=_f(decision.get('confidence'))
    iv=_f(last.get('iv_rank') or last.get('iv_percentile') or (last.get('options') or {}).get('iv_rank'),50)
    trend=_f((((decision.get('components') or {}).get('probability') or {}).get('trend_day_probability')),50)
    if not decision.get('execution_eligible'): family='STAND_DOWN'; structure='NO_TRADE'
    elif bias=='NEUTRAL' and regime=='BALANCE' and iv>=45: family='PREMIUM_SELLING'; structure='IRON_CONDOR'
    elif regime=='EXPANSION' or trend>=65: family='DIRECTIONAL_DEFINED_RISK'; structure='CALL_DEBIT_SPREAD' if bias=='BULLISH' else 'PUT_DEBIT_SPREAD'
    elif iv>=60: family='CREDIT_SPREAD'; structure='BULL_PUT_SPREAD' if bias=='BULLISH' else 'BEAR_CALL_SPREAD'
    else: family='DIRECTIONAL_DEFINED_RISK'; structure='CALL_DEBIT_SPREAD' if bias=='BULLISH' else 'PUT_DEBIT_SPREAD'
    return {'ok':True,'version':VERSION,'evaluated_at':datetime.now(timezone.utc).isoformat(),'ticker':decision.get('ticker','SPX'),'state':'READY' if structure!='NO_TRADE' else 'STAND_DOWN','bias':bias,'regime':regime,'confidence':conf,'iv_rank':iv,'strategy_family':family,'preferred_structure':structure,
      'alternatives':(['BROKEN_WING_BUTTERFLY','VERTICAL_DEBIT_SPREAD'] if structure!='NO_TRADE' else []),'selection_reasons':[f'{bias} institutional bias',f'{regime} market regime',f'IV rank {iv:.1f}',f'Conviction {conf:.1f}'],
      'construction_rules':{'defined_risk_only':True,'zero_dte_max_loss_required':True,'option_chain_validation_required':True,'liquidity_validation_required':True,'credit_received_or_debit_paid_must_be_current':True},
      'guardrails':{'advisory_only':True,'broker_mutation':False,'automatic_execution':False,'human_confirmation_required':True,'kill_switch_authoritative':True}}
