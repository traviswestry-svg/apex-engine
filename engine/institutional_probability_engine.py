"""APEX 19.4 Institutional Probability Engine."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict
import math
VERSION='12.4.0_INSTITUTIONAL_PROBABILITY_ENGINE'
def _f(v,d=0.0):
    try:
        x=float(v); return d if math.isnan(x) or math.isinf(x) else x
    except Exception:return d
def _clip(v):return round(max(5,min(95,v)),1)
def build_probability_engine(last:Dict[str,Any],dealer=None,flow=None,structure=None)->Dict[str,Any]:
    ms=last.get('market_state') or {}; price=_f(ms.get('price') or last.get('price')); pdh=_f(ms.get('previous_day_high')); pdl=_f(ms.get('previous_day_low')); onh=_f(ms.get('overnight_high')); onl=_f(ms.get('overnight_low')); atr=_f(ms.get('atr'),20)
    dealer=dealer or {}; flow=flow or {}; structure=structure or {}
    score=0.0; score += _f(dealer.get('pressure_score'))*.25; score += _f(flow.get('net_flow_score'))*.30
    mig=(structure.get('migration') or {}).get('poc_direction'); score += 15 if mig=='RISING' else -15 if mig=='FALLING' else 0
    acc=(structure.get('acceptance') or {}).get('state',''); score += 15 if 'ABOVE' in acc else -15 if 'BELOW' in acc else 0
    bullish=_clip(50+score/2); bearish=round(100-bullish,1)
    def breakout(level,up=True):
        if not(price and level):return 50.0
        dist=(level-price if up else price-level)/max(1,atr)
        base=(bullish if up else bearish)-max(-15,min(30,dist*20)); return _clip(base)
    trend=_f((structure.get('day_type') or {}).get('trend_day_probability'),50)
    range_remaining=max(0,atr-(_f(ms.get('session_high'),price)-_f(ms.get('session_low'),price))) if price else None
    close='UPPER_QUARTILE' if bullish>=65 else 'LOWER_QUARTILE' if bearish>=65 else 'MID_RANGE'
    confidence=_clip(45+abs(score)*.35)
    warnings=[]
    if not price:warnings.append('PRICE_UNAVAILABLE')
    if not last.get('data_fresh',ms.get('data_fresh',True)):warnings.append('STALE_DATA')
    return {'ok':True,'version':VERSION,'evaluated_at':datetime.now(timezone.utc).isoformat(),'state':'READY' if price and not warnings else 'WARNING' if price else 'DEGRADED','directional':{'bullish':bullish,'bearish':bearish},'new_daily_high_probability':breakout(pdh,True),'new_daily_low_probability':breakout(pdl,False),'break_overnight_high_probability':breakout(onh,True),'break_overnight_low_probability':breakout(onl,False),'trend_day_probability':_clip(trend),'range_day_probability':round(100-_clip(trend),1),'expected_range_remaining':round(range_remaining,2) if range_remaining is not None else None,'expected_close_location':close,'confidence_interval':{'lower':_clip(confidence-10),'point':confidence,'upper':_clip(confidence+10)},'warnings':warnings,'guardrails':{'read_only':True,'broker_mutation':False,'probabilities_are_estimates':True,'stale_data_blocks_execution_use':True}}
