"""APEX 19.1 Institutional Market Structure Engine.

Deterministic, read-only auction-market interpretation over already-computed
profiles, bars, and market state. No network calls and no broker mutation.
"""
from __future__ import annotations
from datetime import datetime, timezone
import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

VERSION = "12.1.0_INSTITUTIONAL_MARKET_STRUCTURE_ENGINE"
SEMANTIC_VERSION = "12.1.0"


def _f(v: Any, d: float = 0.0) -> float:
    try:
        n = float(v)
        return d if math.isnan(n) or math.isinf(n) else n
    except Exception:
        return d


def _rows(profile: Any) -> List[Dict[str, Any]]:
    if isinstance(profile, dict):
        value = profile.get("profile") or profile.get("rows") or profile.get("levels_data") or []
    else:
        value = profile or []
    return [x for x in value if isinstance(x, dict)]


def _levels(profile: Dict[str, Any]) -> Dict[str, Any]:
    return profile.get("levels") if isinstance(profile.get("levels"), dict) else {}


def _profile_summary(profile: Any, name: str, price: float = 0.0) -> Dict[str, Any]:
    if not isinstance(profile, dict) or not profile.get("available", bool(_rows(profile))):
        return {"name": name, "available": False, "state": "UNAVAILABLE"}
    rows = _rows(profile); levels = _levels(profile)
    poc = _f(levels.get("poc") or profile.get("poc")); vah = _f(levels.get("vah") or profile.get("vah")); val = _f(levels.get("val") or profile.get("val"))
    if not (poc and vah and val) and rows:
        parsed=[(_f(r.get("price") or r.get("level")), _f(r.get("activity") or r.get("volume") or r.get("value"))) for r in rows]
        parsed=[x for x in parsed if x[0]>0]
        if parsed:
            poc=max(parsed,key=lambda x:x[1])[0]
            if not val: val=min(x[0] for x in parsed)
            if not vah: vah=max(x[0] for x in parsed)
    width=max(0.0,vah-val)
    location="ABOVE_VALUE" if price and vah and price>vah else "BELOW_VALUE" if price and val and price<val else "IN_VALUE" if price and vah and val else "UNKNOWN"
    return {"name":name,"available":bool(poc and vah and val),"state":"READY" if poc and vah and val else "PARTIAL","poc":round(poc,2) if poc else None,"vah":round(vah,2) if vah else None,"val":round(val,2) if val else None,"value_width":round(width,2),"price_location":location,"hvn":levels.get("hvn") or [],"lvn":levels.get("lvn") or [],"profile_type":profile.get("profile_type"),"bar_count":profile.get("bar_count")}


def build_multi_timeframe_profiles(last: Dict[str, Any]) -> Dict[str, Any]:
    ms=last.get("market_state") or {}; price=_f(ms.get("price") or last.get("price"))
    candidates={
        "1m": last.get("volume_profile_1m") or (last.get("multi_timeframe_profiles") or {}).get("1m"),
        "5m": last.get("volume_profile_5m") or (last.get("multi_timeframe_profiles") or {}).get("5m"),
        "15m": last.get("volume_profile_15m") or (last.get("multi_timeframe_profiles") or {}).get("15m"),
        "session": last.get("volume_profile") or last.get("profile"),
        "previous_day": last.get("previous_day_profile") or last.get("prior_profile"),
        "daily": last.get("daily_volume_profile") or (last.get("multi_timeframe_profiles") or {}).get("daily"),
    }
    summaries=[_profile_summary(v,k,price) for k,v in candidates.items()]
    available=[x for x in summaries if x.get("available")]
    pocs=[x["poc"] for x in available if x.get("poc")]
    vahs=[x["vah"] for x in available if x.get("vah")]
    vals=[x["val"] for x in available if x.get("val")]
    confluence=[]
    for values,label in ((pocs,"POC"),(vahs,"VAH"),(vals,"VAL")):
        for v in values:
            near=[x for x in values if abs(x-v)<=2.0]
            if len(near)>=2:
                level=round(sum(near)/len(near),2)
                if not any(abs(c["level"]-level)<0.5 and c["type"]==label for c in confluence): confluence.append({"type":label,"level":level,"touches":len(near)})
    return {"available":bool(available),"profiles":summaries,"available_count":len(available),"confluence_levels":sorted(confluence,key=lambda x:(-x["touches"],x["level"]))}


def build_poc_value_migration(last: Dict[str, Any], mtf: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
    mtf=mtf or build_multi_timeframe_profiles(last); profiles={x["name"]:x for x in mtf.get("profiles",[]) if x.get("available")}
    cur=profiles.get("session") or profiles.get("15m") or profiles.get("5m"); prev=profiles.get("previous_day") or profiles.get("daily")
    explicit=(last.get("auction_intelligence") or {}).get("poc_migration") or (last.get("market_state") or {}).get("poc_migration")
    if cur and prev:
        delta=round(_f(cur.get("poc"))-_f(prev.get("poc")),2); vah_delta=round(_f(cur.get("vah"))-_f(prev.get("vah")),2); val_delta=round(_f(cur.get("val"))-_f(prev.get("val")),2)
        direction="RISING" if delta>1 else "FALLING" if delta<-1 else "FLAT"
        value_direction="RISING" if vah_delta>1 and val_delta>1 else "FALLING" if vah_delta<-1 and val_delta<-1 else "EXPANDING" if vah_delta>0 and val_delta<0 else "CONTRACTING" if vah_delta<0 and val_delta>0 else "MIXED"
        return {"available":True,"poc_direction":direction,"poc_delta":delta,"value_direction":value_direction,"vah_delta":vah_delta,"val_delta":val_delta,"institutional_read":"ACCEPTANCE_HIGHER" if direction=="RISING" and value_direction=="RISING" else "ACCEPTANCE_LOWER" if direction=="FALLING" and value_direction=="FALLING" else "ROTATIONAL_OR_TRANSITIONAL"}
    if explicit:
        return {"available":True,"poc_direction":str(explicit).upper(),"poc_delta":None,"value_direction":"UNKNOWN","institutional_read":"UPSTREAM_MIGRATION_SIGNAL"}
    return {"available":False,"state":"INSUFFICIENT_PROFILE_HISTORY"}


def _bar(row: Dict[str, Any]) -> Optional[Dict[str,float]]:
    o=_f(row.get("open",row.get("o"))); h=_f(row.get("high",row.get("h"))); l=_f(row.get("low",row.get("l"))); c=_f(row.get("close",row.get("c"))); v=_f(row.get("volume",row.get("v")))
    if not(o and h and l and c and h>=l): return None
    return {"open":o,"high":h,"low":l,"close":c,"volume":v}


def _bars(last: Dict[str, Any]) -> List[Dict[str,float]]:
    raw=last.get("bars") or last.get("candles") or (last.get("chart") or {}).get("bars") or []
    return [b for b in (_bar(x) for x in raw if isinstance(x,dict)) if b]


def build_opening_type(last: Dict[str, Any], mtf: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
    bars=_bars(last); ms=last.get("market_state") or {}; open_price=_f(ms.get("session_open") or last.get("open") or (bars[0]["open"] if bars else 0)); price=_f(ms.get("price") or last.get("price") or (bars[-1]["close"] if bars else 0))
    prev=last.get("previous_day_profile") or last.get("prior_profile") or {}; pl=_levels(prev); vah=_f(pl.get("vah") or prev.get("vah") or ms.get("previous_day_vah")); val=_f(pl.get("val") or prev.get("val") or ms.get("previous_day_val"))
    if not(open_price and price): return {"available":False,"state":"INSUFFICIENT_OPEN_DATA"}
    first=bars[:5]; initial_high=max((x["high"] for x in first),default=max(open_price,price)); initial_low=min((x["low"] for x in first),default=min(open_price,price)); displacement=price-open_price; initial_range=max(0.01,initial_high-initial_low)
    outside="ABOVE_VALUE" if vah and open_price>vah else "BELOW_VALUE" if val and open_price<val else "IN_VALUE" if vah and val else "UNKNOWN"
    drive=abs(displacement)>=max(4.0,initial_range*0.75)
    rejection=(outside=="ABOVE_VALUE" and price<(vah or price+1)) or (outside=="BELOW_VALUE" and price>(val or price-1))
    if rejection: typ="OPEN_REJECTION_REVERSE"
    elif outside!="IN_VALUE" and drive: typ="OPEN_DRIVE"
    elif outside!="IN_VALUE": typ="OPEN_TEST_DRIVE"
    elif drive: typ="OPEN_AUCTION_IN_RANGE_EXPANSION"
    else: typ="OPEN_AUCTION_IN_RANGE"
    direction="BULLISH" if displacement>0 else "BEARISH" if displacement<0 else "NEUTRAL"
    confidence=min(90.0,50+abs(displacement)/initial_range*20)
    return {"available":True,"type":typ,"direction":direction,"confidence":round(confidence,1),"open_location":outside,"open_price":round(open_price,2),"displacement":round(displacement,2),"initial_range":round(initial_range,2)}


def build_auction_defects(last: Dict[str, Any]) -> Dict[str, Any]:
    bars=_bars(last)
    if len(bars)<3: return {"available":False,"state":"INSUFFICIENT_BARS","poor_high":False,"poor_low":False,"single_prints":[],"buying_tail":None,"selling_tail":None}
    high=max(x["high"] for x in bars); low=min(x["low"] for x in bars); near_high=sum(1 for x in bars if abs(x["high"]-high)<=0.5); near_low=sum(1 for x in bars if abs(x["low"]-low)<=0.5)
    top=next((x for x in reversed(bars) if abs(x["high"]-high)<=0.5),bars[-1]); bot=next((x for x in bars if abs(x["low"]-low)<=0.5),bars[0])
    top_range=max(.01,top["high"]-top["low"]); bot_range=max(.01,bot["high"]-bot["low"])
    selling_tail=round(top["high"]-max(top["open"],top["close"]),2); buying_tail=round(min(bot["open"],bot["close"])-bot["low"],2)
    single=[]
    for a,b in zip(bars,bars[1:]):
        if b["low"]>a["high"]: single.append({"low":round(a["high"],2),"high":round(b["low"],2),"direction":"UP"})
        elif b["high"]<a["low"]: single.append({"low":round(b["high"],2),"high":round(a["low"],2),"direction":"DOWN"})
    return {"available":True,"poor_high":near_high>=2 and selling_tail/top_range<.15,"poor_low":near_low>=2 and buying_tail/bot_range<.15,"single_prints":single[-10:],"buying_tail":{"points":buying_tail,"strong":buying_tail/bot_range>=.35},"selling_tail":{"points":selling_tail,"strong":selling_tail/top_range>=.35},"auction_complete_high":selling_tail/top_range>=.35,"auction_complete_low":buying_tail/bot_range>=.35}


def build_acceptance_rejection(last: Dict[str, Any], mtf: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
    mtf=mtf or build_multi_timeframe_profiles(last); profiles={x["name"]:x for x in mtf.get("profiles",[]) if x.get("available")}; p=profiles.get("session") or profiles.get("15m") or profiles.get("5m")
    ms=last.get("market_state") or {}; price=_f(ms.get("price") or last.get("price")); bars=_bars(last)
    if not p or not price: return {"available":False,"state":"NO_REFERENCE_PROFILE"}
    vah=_f(p.get("vah")); val=_f(p.get("val")); poc=_f(p.get("poc")); closes=[x["close"] for x in bars[-5:]] or [price]
    above=sum(1 for c in closes if c>vah); below=sum(1 for c in closes if c<val); near_poc=sum(1 for c in closes if abs(c-poc)<=2)
    if above>=3: state="ACCEPTANCE_ABOVE_VALUE"; direction="BULLISH"
    elif below>=3: state="ACCEPTANCE_BELOW_VALUE"; direction="BEARISH"
    elif price>vah and above<3: state="TESTING_ABOVE_VALUE"; direction="NEUTRAL"
    elif price<val and below<3: state="TESTING_BELOW_VALUE"; direction="NEUTRAL"
    elif near_poc>=3: state="POC_ACCEPTANCE"; direction="NEUTRAL"
    else: state="VALUE_ROTATION"; direction="NEUTRAL"
    return {"available":True,"state":state,"direction":direction,"reference_profile":p["name"],"closes_observed":len(closes),"above_value_closes":above,"below_value_closes":below,"poc_acceptance_closes":near_poc}


def build_day_type_probability(last: Dict[str, Any], migration: Dict[str,Any], opening: Dict[str,Any], acceptance: Dict[str,Any]) -> Dict[str, Any]:
    ms=last.get("market_state") or {}; price=_f(ms.get("price") or last.get("price")); high=_f(ms.get("session_high") or ms.get("high")); low=_f(ms.get("session_low") or ms.get("low")); rng=max(0,high-low)
    atr=_f(ms.get("atr") or last.get("atr") or (last.get("volatility") or {}).get("atr")); expansion=(rng/atr) if atr else 0
    trend=35.0; balance=65.0
    if opening.get("type") in {"OPEN_DRIVE","OPEN_AUCTION_IN_RANGE_EXPANSION"}: trend+=20; balance-=20
    if acceptance.get("state") in {"ACCEPTANCE_ABOVE_VALUE","ACCEPTANCE_BELOW_VALUE"}: trend+=20; balance-=20
    if migration.get("institutional_read") in {"ACCEPTANCE_HIGHER","ACCEPTANCE_LOWER"}: trend+=15; balance-=15
    if expansion>=.8: trend+=10; balance-=10
    trend=max(5,min(95,trend)); balance=100-trend
    return {"available":True,"trend_day_probability":round(trend,1),"balance_day_probability":round(balance,1),"range_expansion_atr":round(expansion,2) if atr else None,"classification":"TREND_FAVORED" if trend>=65 else "BALANCE_FAVORED" if balance>=65 else "MIXED"}


def build_structure_levels(last: Dict[str,Any], mtf: Dict[str,Any], defects: Dict[str,Any]) -> Dict[str,Any]:
    ms=last.get("market_state") or {}; price=_f(ms.get("price") or last.get("price")); levels=[]
    def add(kind,val,weight=1):
        v=_f(val)
        if v: levels.append({"type":kind,"level":round(v,2),"distance":round(v-price,2) if price else None,"weight":weight})
    for p in mtf.get("profiles",[]):
        if p.get("available"):
            add(p["name"].upper()+"_POC",p.get("poc"),3); add(p["name"].upper()+"_VAH",p.get("vah"),2); add(p["name"].upper()+"_VAL",p.get("val"),2)
            for v in (p.get("hvn") or [])[:3]: add("HVN",v,2)
            for v in (p.get("lvn") or [])[:3]: add("LVN_FAST_ZONE",v,1)
    for key,label in (("previous_day_high","PDH"),("previous_day_low","PDL"),("overnight_high","ONH"),("overnight_low","ONL")):
        add(label,ms.get(key) or (last.get("overnight") or {}).get(key),3)
    dedup={}
    for x in levels:
        key=(x["type"],x["level"]); dedup[key]=x
    ordered=sorted(dedup.values(),key=lambda x:(abs(x["distance"]) if x["distance"] is not None else 1e9,-x["weight"]))
    supports=[x for x in ordered if x["distance"] is not None and x["distance"]<=0][:8]
    resistances=[x for x in ordered if x["distance"] is not None and x["distance"]>0][:8]
    targets={"upside":resistances[:3],"downside":supports[:3]}
    return {"available":bool(ordered),"supports":supports,"resistances":resistances,"targets":targets,"all_levels":ordered[:30]}


def build_institutional_market_structure(last: Dict[str,Any]) -> Dict[str,Any]:
    last=last if isinstance(last,dict) else {}; mtf=build_multi_timeframe_profiles(last); migration=build_poc_value_migration(last,mtf); opening=build_opening_type(last,mtf); defects=build_auction_defects(last); acceptance=build_acceptance_rejection(last,mtf); day=build_day_type_probability(last,migration,opening,acceptance); levels=build_structure_levels(last,mtf,defects)
    direction="BULLISH" if acceptance.get("direction")=="BULLISH" or migration.get("institutional_read")=="ACCEPTANCE_HIGHER" else "BEARISH" if acceptance.get("direction")=="BEARISH" or migration.get("institutional_read")=="ACCEPTANCE_LOWER" else opening.get("direction","NEUTRAL")
    warnings=[]
    if not mtf.get("available"): warnings.append("NO_PROFILE_DATA")
    if defects.get("poor_high"): warnings.append("POOR_HIGH_UNFINISHED_AUCTION")
    if defects.get("poor_low"): warnings.append("POOR_LOW_UNFINISHED_AUCTION")
    stale=bool(last.get("data_fresh") is False or (last.get("market_state") or {}).get("data_fresh") is False)
    if stale: warnings.append("STALE_DATA")
    return {"ok":True,"version":VERSION,"semantic_version":SEMANTIC_VERSION,"evaluated_at":datetime.now(timezone.utc).isoformat(),"ticker":str(last.get("ticker") or "SPX"),"state":"READY" if mtf.get("available") else "DEGRADED","direction":direction,"warnings":warnings,"multi_timeframe_profiles":mtf,"poc_value_migration":migration,"opening_type":opening,"auction_defects":defects,"acceptance_rejection":acceptance,"day_type_probability":day,"structure_levels":levels,"guardrails":{"read_only":True,"broker_mutation":False,"automatic_execution":False,"stale_data_blocks_use":stale}}
