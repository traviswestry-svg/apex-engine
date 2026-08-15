"""APEX 20.1 Institutional Execution Optimizer (advisory only)."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict
from .institutional_decision_engine import build_institutional_decision
VERSION='13.1.0_INSTITUTIONAL_EXECUTION_OPTIMIZER'

def _f(v,d=0.0):
    try:return float(v)
    except:return d

def build_execution_plan(last:Dict[str,Any], decision:Dict[str,Any]|None=None)->Dict[str,Any]:
    last=last if isinstance(last,dict) else {}
    decision=decision or build_institutional_decision(last)
    bias=decision.get('bias','NEUTRAL'); confidence=_f(decision.get('confidence'))
    levels=decision.get('levels') or {}; market=last.get('market_state') or {}
    price=_f(last.get('price') or last.get('spx') or last.get('last') or market.get('price'))
    atr=_f(last.get('atr') or (last.get('market_state') or {}).get('atr'),10.0)
    supports=levels.get('supports') or []; resistances=levels.get('resistances') or []
    def _prices(rows):
        values=[]
        for row in rows:
            raw=row.get('price') if isinstance(row,dict) else row
            value=_f(raw)
            if value>0: values.append(value)
        return values
    support_prices=_prices(supports); resistance_prices=_prices(resistances)
    anchor=(max(support_prices,default=price-atr*.35)
            if bias=='BULLISH' else min(resistance_prices,default=price+atr*.35))
    direction=1 if bias=='BULLISH' else -1
    entry=round(anchor,2); stop=round(entry-direction*max(2.0,atr*.35),2)
    risk=abs(entry-stop); targets=[round(entry+direction*risk*r,2) for r in (1.0,1.75,2.5)]
    eligible=bool(decision.get('execution_eligible')) and bias in ('BULLISH','BEARISH')
    valid_price=price>0
    plan_valid=bool(eligible and valid_price and entry>0 and stop>0 and all(t>0 for t in targets))
    blockers=list(decision.get('blocking_reasons',[]) if not eligible else [])
    if not valid_price and 'UNDERLYING_PRICE_UNAVAILABLE' not in blockers:
        blockers.append('UNDERLYING_PRICE_UNAVAILABLE')
    if not plan_valid and 'INCOMPLETE_TRADE_PLAN' not in blockers:
        blockers.append('INCOMPLETE_TRADE_PLAN')
    reference={'entry_zone':{'anchor':entry,'tolerance_points':round(max(1.0,atr*.12),2)},
               'invalidation':stop,'targets':{'tp1':targets[0],'tp2':targets[1],'tp3':targets[2]}} if valid_price else None
    return {'ok':True,'version':VERSION,'evaluated_at':datetime.now(timezone.utc).isoformat(),'ticker':decision.get('ticker','SPX'),
      'state':'READY' if plan_valid else 'STAND_DOWN','bias':bias,'confidence':confidence,'entry_method':'PULLBACK_CONFIRMATION','entry_zone':reference['entry_zone'] if plan_valid else None,
      'invalidation':reference['invalidation'] if plan_valid else None,'targets':reference['targets'] if plan_valid else {},'reference_plan':reference,'plan_valid':plan_valid,'risk_reward':{'tp1':1.0,'tp2':1.75,'tp3':2.5} if plan_valid else {},
      'sizing':{'mode':'ADVISORY','confidence_tier':'HIGH' if confidence>=80 else 'MODERATE' if confidence>=65 else 'LOW','max_contracts':0,'requires_account_risk_validation':True},
      'order_guidance':{'limit_order_preferred':True,'do_not_chase':True,'confirmation_required':True,'partial_exit_plan':'Scale 40%/35%/25% at TP1/TP2/TP3'},
      'blocking_reasons':blockers,'guardrails':{'advisory_only':True,'broker_mutation':False,'automatic_execution':False,'human_confirmation_required':True,'kill_switch_authoritative':True,'invalid_plan_hidden':True}}
