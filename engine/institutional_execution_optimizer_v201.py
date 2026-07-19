"""APEX 20.1 Institutional Execution Optimizer (advisory only)."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict
from .institutional_decision_engine_v20 import build_institutional_decision
VERSION='13.1.0_INSTITUTIONAL_EXECUTION_OPTIMIZER'

def _f(v,d=0.0):
    try:return float(v)
    except:return d

def build_execution_plan(last:Dict[str,Any], decision:Dict[str,Any]|None=None)->Dict[str,Any]:
    last=last if isinstance(last,dict) else {}
    decision=decision or build_institutional_decision(last)
    bias=decision.get('bias','NEUTRAL'); confidence=_f(decision.get('confidence'))
    levels=decision.get('levels') or {}; price=_f(last.get('price') or last.get('spx') or last.get('last'))
    atr=_f(last.get('atr') or (last.get('market_state') or {}).get('atr'),10.0)
    supports=levels.get('supports') or []; resistances=levels.get('resistances') or []
    anchor=(max([_f(x.get('price',x)) for x in supports if isinstance(x,(dict,int,float)) and _f(x.get('price',x) if isinstance(x,dict) else x)>0],default=price-atr*.35)
            if bias=='BULLISH' else min([_f(x.get('price',x)) for x in resistances if isinstance(x,(dict,int,float)) and _f(x.get('price',x) if isinstance(x,dict) else x)>0],default=price+atr*.35))
    direction=1 if bias=='BULLISH' else -1
    entry=round(anchor,2); stop=round(entry-direction*max(2.0,atr*.35),2)
    risk=abs(entry-stop); targets=[round(entry+direction*risk*r,2) for r in (1.0,1.75,2.5)]
    eligible=bool(decision.get('execution_eligible')) and bias in ('BULLISH','BEARISH')
    return {'ok':True,'version':VERSION,'evaluated_at':datetime.now(timezone.utc).isoformat(),'ticker':decision.get('ticker','SPX'),
      'state':'READY' if eligible else 'STAND_DOWN','bias':bias,'confidence':confidence,'entry_method':'PULLBACK_CONFIRMATION','entry_zone':{'anchor':entry,'tolerance_points':round(max(1.0,atr*.12),2)},
      'invalidation':stop,'targets':{'tp1':targets[0],'tp2':targets[1],'tp3':targets[2]},'risk_reward':{'tp1':1.0,'tp2':1.75,'tp3':2.5},
      'sizing':{'mode':'ADVISORY','confidence_tier':'HIGH' if confidence>=80 else 'MODERATE' if confidence>=65 else 'LOW','max_contracts':0,'requires_account_risk_validation':True},
      'order_guidance':{'limit_order_preferred':True,'do_not_chase':True,'confirmation_required':True,'partial_exit_plan':'Scale 40%/35%/25% at TP1/TP2/TP3'},
      'blocking_reasons':decision.get('blocking_reasons',[]) if not eligible else [],'guardrails':{'advisory_only':True,'broker_mutation':False,'automatic_execution':False,'human_confirmation_required':True,'kill_switch_authoritative':True}}
