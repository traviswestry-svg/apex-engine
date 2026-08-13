"""APEX 16.1 Live Mission Control and Institutional Confluence Score.

Read-only composition layer joining immutable institutional pressure, market
state, playbook, and current engine evidence into one deterministic desk view.
No recommendation, confidence, risk, position, or broker mutation occurs.
"""
from __future__ import annotations
import hashlib, json, math
from typing import Any
from . import institutional_order_flow_intelligence as iofi
from . import institutional_market_state_engine as imse
from . import institutional_playbook_engine as ipe
from . import adaptive_trade_management as atm
from . import portfolio_risk_intelligence as pri
from . import explainable_intelligence_assistant as eia
from . import performance_intelligence as pi
from . import live_operations as lo
from . import strategy_promotion_governance as spg
from . import broker_synchronized_position_state as bsps
from . import confirmation_gated_execution as cge
from . import institutional_autonomous_desk as iad
from . import sandbox_execution_validation as sev

VERSION='16.1.16.1'; SCHEMA_VERSION='apex.mission_control.v1'
WEIGHTS={
 'institutional_pressure':0.22,'pressure_conviction':0.12,'market_state_confidence':0.14,
 'market_state_stability':0.10,'playbook_quality':0.18,'playbook_compatibility':0.10,
 'decision_confidence':0.08,'structure_alignment':0.06,
}

def _num(v, default=0.0):
    try:
        x=float(v); return x if math.isfinite(x) else default
    except Exception:return default

def _clamp(v,lo=0.0,hi=100.0): return max(lo,min(hi,float(v)))
def _pick(d:dict[str,Any],*keys,default=None):
    for k in keys:
        cur=d
        ok=True
        for p in k.split('.'):
            if isinstance(cur,dict) and p in cur: cur=cur[p]
            else: ok=False; break
        if ok and cur is not None:return cur
    return default

def _direction(label:Any)->int:
    s=str(label or '').upper()
    if any(x in s for x in ('BULL','CALL','LONG','UP')): return 1
    if any(x in s for x in ('BEAR','PUT','SHORT','DOWN')): return -1
    return 0

def status():
    return {'status':'READY','engine':'LIVE_MISSION_CONTROL','build_version':VERSION,
      'schema_version':SCHEMA_VERSION,'deterministic':True,'future_information_allowed':False,
      'recommendation_mutation_enabled':False,'confidence_mutation_enabled':False,
      'live_position_mutation_enabled':False,'broker_order_submission_enabled':False,
      'production_effect':'NONE','confluence_weights':WEIGHTS,'explainable_intelligence':eia.status()}

def confluence(*,pressure:dict|None, market_state:dict|None, playbook:dict|None, engine_snapshot:dict|None=None):
    p=pressure or {}; m=market_state or {}; b=playbook or {}; e=engine_snapshot or {}
    ips=_num(_pick(p,'institutional_pressure_score','result.institutional_pressure_score'),50)
    pconv=_num(_pick(p,'conviction','result.conviction'))
    msconf=_num(_pick(m,'confidence','state_confidence','active_state_confidence'))
    msstab=_num(_pick(m,'stability','stability_index','regime_stability_index'))
    pqs=_num(_pick(b,'playbook_quality_score','pqs','quality_score'))
    compat=_num(_pick(b,'state_compatibility','imse_compatibility','compatibility_score'))
    dconf=_num(_pick(e,'confidence','decision_confidence','trade_director.confidence'))
    structure=_num(_pick(e,'structure_alignment','auction_alignment','confluence.structure_alignment'))
    values={'institutional_pressure':ips,'pressure_conviction':pconv,'market_state_confidence':msconf,
      'market_state_stability':msstab,'playbook_quality':pqs,'playbook_compatibility':compat,
      'decision_confidence':dconf,'structure_alignment':structure}
    available={k:v for k,v in values.items() if v>0 or k=='institutional_pressure'}
    weight_total=sum(WEIGHTS[k] for k in available)
    score=sum(values[k]*WEIGHTS[k] for k in available)/(weight_total or 1)
    dirs=[_direction(_pick(p,'bias','result.bias')),_direction(_pick(b,'direction')),_direction(_pick(e,'recommendation','bias','trade_director.action'))]
    nonzero=[x for x in dirs if x]
    agreement=100.0 if not nonzero else 100*max(nonzero.count(1),nonzero.count(-1))/len(nonzero)
    score=_clamp(score*(0.8+0.2*agreement/100))
    if score>=90: grade='A+'
    elif score>=82: grade='A'
    elif score>=74: grade='B+'
    elif score>=65: grade='B'
    elif score>=55: grade='C'
    else: grade='STAND_DOWN'
    components=[{'name':k,'score':round(values[k],2),'weight':WEIGHTS[k],'weighted':round(values[k]*WEIGHTS[k],2),'available':k in available} for k in WEIGHTS]
    return {'institutional_confluence_score':round(score,2),'grade':grade,'directional_agreement_pct':round(agreement,2),
      'coverage_pct':round(100*weight_total/sum(WEIGHTS.values()),2),'components':components}

def briefing(*,pressure:dict|None,market_state:dict|None,playbook:dict|None,ics:dict,engine_snapshot:dict|None=None):
    p=pressure or {}; m=market_state or {}; b=playbook or {}; e=engine_snapshot or {}
    state=_pick(m,'active_state','state_name','active_state_name',default='UNAVAILABLE')
    pb=_pick(b,'active_playbook','playbook_name',default='UNAVAILABLE')
    bias=_pick(p,'bias','result.bias',default='NEUTRAL')
    action=_pick(e,'trade_director.action','recommendation','directive',default='WAIT')
    invalidation=_pick(b,'invalidation','invalidation_conditions',default=[])
    if isinstance(invalidation,list): invalidation='; '.join(str(x) for x in invalidation[:2])
    return {'headline':f"{state} | {pb}", 'market_read':f"Institutional pressure is {bias} with confluence graded {ics['grade']} ({ics['institutional_confluence_score']}).",
      'directive':str(action),'primary_invalidation':invalidation or 'Evidence Not Available',
      'evidence_only':True,'generated_from_immutable_sources':True}

def position_monitor(engine_snapshot:dict|None=None):
    e=engine_snapshot or {}; pos=_pick(e,'position','open_position','trade_director.position',default={})
    if not isinstance(pos,dict) or not pos:
        return {'status':'FLAT','position_open':False,'advisory_only':True,'broker_effect':'NONE'}
    entry=_num(pos.get('entry_price')); mark=_num(pos.get('mark_price') or pos.get('current_price'))
    side=str(pos.get('side') or 'LONG').upper(); qty=_num(pos.get('quantity'),1)
    pnl=((mark-entry) if side in ('LONG','CALL','BUY') else (entry-mark))*qty*100 if entry and mark else _num(pos.get('unrealized_pnl'))
    return {'status':'OPEN','position_open':True,'symbol':pos.get('symbol','SPX'),'side':side,'quantity':qty,
      'entry_price':entry or None,'mark_price':mark or None,'unrealized_pnl':round(pnl,2),'time_in_trade_seconds':_num(pos.get('time_in_trade_seconds')),
      'remaining_edge':_pick(pos,'remaining_edge',default='UNMEASURED'),'advisory_only':True,'broker_effect':'NONE'}

def dashboard(symbol='SPX',engine_snapshot:dict|None=None):
    p=iofi.current(symbol); m=imse.current(symbol); b=ipe.current(symbol)
    pp=p if p.get('ok') else None; mm=m if m.get('ok') else None; bb=b if b.get('ok') else None
    ics=confluence(pressure=pp,market_state=mm,playbook=bb,engine_snapshot=engine_snapshot)
    result={'ok':True,'status':'READY','symbol':symbol,'institutional_pressure':pp,'market_state':mm,'playbook':bb,
      'institutional_confluence':ics,'briefing':briefing(pressure=pp,market_state=mm,playbook=bb,ics=ics,engine_snapshot=engine_snapshot),
      'position_monitor':position_monitor(engine_snapshot),'portfolio_risk':pri.evaluate(engine_snapshot or {}),'adaptive_trade_management':atm.evaluate({**(engine_snapshot or {}),'institutional_confluence':ics,'pressure':pp or {},'market_state':mm or {},'playbook':bb or {}}),
      'structure':_pick(engine_snapshot or {},'structure','levels',default={}),
      'trade_director':_pick(engine_snapshot or {},'trade_director','active_trade_director',default={}),'explainable_intelligence':{'status':'READY','supported_intents':list(eia.SUPPORTED_INTENTS),'evidence_grounded_only':True},'performance_intelligence':pi.analyze_stored(symbol),'live_operations':lo.latest(symbol),'strategy_promotion':spg.dashboard(),'broker_sync':bsps.latest('PRIMARY','ETRADE'),'confirmation_gated_execution':cge.dashboard(10),'sandbox_execution_validation':sev.dashboard('PRIMARY',5),'institutional_autonomous_desk':iad.dashboard(8),'safety':status()}
    result['integrity_hash']=hashlib.sha256(json.dumps(result,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
    return result
