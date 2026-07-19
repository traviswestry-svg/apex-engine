"""APEX 19.5 Adaptive Learning Engine v2 — bounded, audit-friendly calibration."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, Iterable
import math
VERSION='12.5.0_ADAPTIVE_LEARNING_ENGINE_V2'
def _f(v,d=0.0):
    try:
        x=float(v); return d if math.isnan(x) or math.isinf(x) else x
    except Exception:return d
def build_adaptive_learning_v2(last:Dict[str,Any], history=None)->Dict[str,Any]:
    rows=history if isinstance(history,list) else last.get('recommendation_history') or last.get('graded_recommendations') or []
    rows=[x for x in rows if isinstance(x,dict) and str(x.get('outcome','')).upper() not in ('NOT_EXECUTABLE','PENDING','')]
    buckets={}; wins=0
    for r in rows:
        won=str(r.get('outcome') or r.get('result')).upper() in ('WIN','WON','SUCCESS','PROFIT'); wins+=int(won)
        setup=str(r.get('setup') or r.get('strategy_family') or 'UNKNOWN'); regime=str(r.get('regime') or 'UNKNOWN'); hour=str(r.get('hour') or r.get('time_bucket') or 'UNKNOWN')
        for kind,key in (('setup',setup),('regime',regime),('time',hour)):
            b=buckets.setdefault(kind,{}).setdefault(key,{'samples':0,'wins':0}); b['samples']+=1;b['wins']+=int(won)
    insights=[]
    for kind,vals in buckets.items():
        for key,b in vals.items():
            rate=b['wins']/b['samples']*100
            if b['samples']>=5: insights.append({'dimension':kind,'value':key,'samples':b['samples'],'win_rate':round(rate,1),'confidence':'HIGH' if b['samples']>=30 else 'MEDIUM'})
    insights.sort(key=lambda x:(x['win_rate'],x['samples']),reverse=True)
    n=len(rows); raw=round(wins/n*100,1) if n else None
    # Bounded suggestions only; no live self-modification.
    suggestions=[]
    for x in insights[:8]:
        delta=max(-10,min(10,(x['win_rate']-50)*.2))
        suggestions.append({**x,'suggested_weight_delta':round(delta,2),'applied':False})
    readiness='READY_FOR_REVIEW' if n>=30 else 'COLLECTING_DATA'
    return {'ok':True,'version':VERSION,'evaluated_at':datetime.now(timezone.utc).isoformat(),'state':'READY' if n else 'DEGRADED','sample_size':n,'win_rate':raw,'learning_readiness':readiness,'best_patterns':insights[:10],'weight_suggestions':suggestions,'calibration':{'automatic_application':False,'max_suggested_delta_pct':10,'not_executable_excluded':True,'minimum_samples':30},'guardrails':{'read_only':True,'broker_mutation':False,'automatic_weight_changes':False,'human_approval_required':True,'lookahead_protection_required':True}}
