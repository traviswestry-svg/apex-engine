"""APEX 19.2 Institutional Dealer Positioning Engine (read-only)."""
from __future__ import annotations
from datetime import datetime, timezone
import math
from typing import Any, Dict, List
VERSION='12.2.0_INSTITUTIONAL_DEALER_POSITIONING_ENGINE'

def _f(v,d=0.0):
    try:
        x=float(v); return d if math.isnan(x) or math.isinf(x) else x
    except Exception:return d

def _first(d,*keys):
    for k in keys:
        v=d.get(k)
        if v is not None:return v
    return None

def build_dealer_positioning(last:Dict[str,Any])->Dict[str,Any]:
    src=last.get('dealer_positioning') or last.get('gamma') or last.get('gamma_context') or {}
    ms=last.get('market_state') or {}; price=_f(_first(ms,'price','spot') or last.get('price'))
    flip=_f(_first(src,'gamma_flip','flip','zero_gamma')); call_wall=_f(_first(src,'call_wall','callwall','largest_call_gamma'))
    put_wall=_f(_first(src,'put_wall','putwall','largest_put_gamma')); net_gex=_f(_first(src,'net_gex','gex','gamma_exposure'))
    dex=_f(_first(src,'dealer_delta','dex','delta_exposure')); vex=_f(_first(src,'vanna','vex','vanna_exposure')); chex=_f(_first(src,'charm','chex','charm_exposure'))
    available=bool(price and any((flip,call_wall,put_wall,net_gex,dex,vex,chex)))
    gamma_regime='POSITIVE_GAMMA' if net_gex>0 else 'NEGATIVE_GAMMA' if net_gex<0 else 'UNKNOWN'
    vol_regime='MEAN_REVERTING' if net_gex>0 else 'EXPANSION_RISK' if net_gex<0 else 'UNKNOWN'
    pressure=0.0
    if flip and price: pressure += 20 if price>flip else -20
    pressure += 20 if dex>0 else -20 if dex<0 else 0
    pressure += 10 if vex>0 else -10 if vex<0 else 0
    pressure += 10 if chex>0 else -10 if chex<0 else 0
    pressure=max(-100,min(100,pressure))
    hedge='BUYING_PRESSURE' if pressure>=20 else 'SELLING_PRESSURE' if pressure<=-20 else 'BALANCED'
    squeeze=0
    if net_gex<0:squeeze+=35
    if price and call_wall and 0 <= call_wall-price <= max(10,price*.004):squeeze+=25
    if dex>0:squeeze+=20
    if vex>0:squeeze+=10
    pin_level=None; pin_prob=0
    levels=[x for x in (flip,call_wall,put_wall) if x]
    if price and levels:
        pin_level=min(levels,key=lambda x:abs(x-price)); dist=abs(pin_level-price)
        pin_prob=round(max(0,80-dist/max(1,price*.001)*10),1)
    bias='BULLISH' if pressure>=20 else 'BEARISH' if pressure<=-20 else 'NEUTRAL'
    warnings=[]
    if not available:warnings.append('DEALER_DATA_UNAVAILABLE')
    if not last.get('data_fresh',ms.get('data_fresh',True)):warnings.append('STALE_DATA')
    return {'ok':True,'version':VERSION,'evaluated_at':datetime.now(timezone.utc).isoformat(),'available':available,'state':'READY' if available and not warnings else 'WARNING' if available else 'DEGRADED','price':price or None,'gamma_flip':flip or None,'zero_gamma':flip or None,'call_wall':call_wall or None,'put_wall':put_wall or None,'net_gex':net_gex,'dealer_delta':dex,'vanna_exposure':vex,'charm_exposure':chex,'gamma_regime':gamma_regime,'volatility_regime':vol_regime,'dealer_hedging_pressure':hedge,'pressure_score':round(pressure,1),'bias':bias,'squeeze_probability':min(95,squeeze),'pin_risk':{'level':pin_level,'probability':pin_prob},'warnings':warnings,'guardrails':{'read_only':True,'broker_mutation':False,'changes_execution_permissions':False}}
