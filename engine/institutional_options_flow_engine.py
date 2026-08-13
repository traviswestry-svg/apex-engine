"""APEX 19.3 Institutional Options Flow Intelligence (read-only)."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List
import math
VERSION='12.3.0_INSTITUTIONAL_OPTIONS_FLOW_INTELLIGENCE'
def _f(v,d=0.0):
    try:
        x=float(v); return d if math.isnan(x) or math.isinf(x) else x
    except Exception:return d

def _events(last):
    for key in ('flow_tape','options_flow','flow_events','quantdata_flow'):
        v=last.get(key)
        if isinstance(v,list): return [x for x in v if isinstance(x,dict)]
        if isinstance(v,dict):
            rows=v.get('events') or v.get('rows') or v.get('tape')
            if isinstance(rows,list):return [x for x in rows if isinstance(x,dict)]
    return []
def build_options_flow_intelligence(last:Dict[str,Any])->Dict[str,Any]:
    rows=_events(last); scored=[]; bull=bear=0.0
    for e in rows:
        side=str(e.get('side') or e.get('sentiment') or e.get('direction') or '').upper()
        typ=str(e.get('type') or e.get('execution_type') or '').upper()
        premium=_f(e.get('premium') or e.get('notional') or e.get('value')); size=_f(e.get('size') or e.get('contracts'))
        at_ask=bool(e.get('at_ask') or e.get('ask_side')); at_bid=bool(e.get('at_bid') or e.get('bid_side'))
        opening=e.get('opening') if e.get('opening') is not None else e.get('open_interest_change',0)>0
        repeat=_f(e.get('repeat_count') or e.get('cluster_size') or 1)
        q=min(100,25+(20 if 'SWEEP' in typ else 8)+(15 if premium>=250000 else 8 if premium>=100000 else 0)+(10 if repeat>=3 else 0)+(10 if opening else 0))
        direction='BULLISH' if side in ('CALL','BULLISH','BUY') or at_ask else 'BEARISH' if side in ('PUT','BEARISH','SELL') or at_bid else 'NEUTRAL'
        intent='SPECULATION' if opening and q>=55 else 'POSSIBLE_HEDGE' if not opening else 'UNRESOLVED'
        weight=q*max(1,premium/100000)
        if direction=='BULLISH':bull+=weight
        elif direction=='BEARISH':bear+=weight
        scored.append({'direction':direction,'quality':round(q,1),'premium':premium,'type':typ or 'UNKNOWN','opening':bool(opening),'intent':intent,'repeat_count':repeat})
    total=bull+bear; net=((bull-bear)/total*100) if total else 0
    persistence=sum(1 for x in scored if x['repeat_count']>=3 or x['quality']>=70)
    bias='BULLISH' if net>=15 else 'BEARISH' if net<=-15 else 'NEUTRAL'
    trap='BULL_TRAP_RISK' if bias=='BULLISH' and last.get('market_state',{}).get('trend')=='DOWN' else 'BEAR_TRAP_RISK' if bias=='BEARISH' and last.get('market_state',{}).get('trend')=='UP' else 'NONE'
    warnings=[] if rows else ['FLOW_DATA_UNAVAILABLE']
    return {'ok':True,'version':VERSION,'evaluated_at':datetime.now(timezone.utc).isoformat(),'available':bool(rows),'state':'READY' if rows else 'DEGRADED','event_count':len(rows),'bias':bias,'net_flow_score':round(net,1),'bullish_weight':round(bull,1),'bearish_weight':round(bear,1),'persistence_score':round(min(100,persistence/max(1,len(rows))*100),1),'institutional_clusters':sum(1 for x in scored if x['repeat_count']>=3),'high_quality_events':sum(1 for x in scored if x['quality']>=70),'trap_detection':trap,'events':sorted(scored,key=lambda x:x['quality'],reverse=True)[:25],'warnings':warnings,'guardrails':{'read_only':True,'broker_mutation':False,'intent_is_inference':True}}
