"""APEX 69.10.31 — Counterfactual Cluster Discrimination Intelligence.

Read-only comparison of missed-opportunity and protective-abstention clusters.
Only decision-time fields are eligible as discriminators. Outcome excursion fields
are summarized separately and are never used to promote, calibrate, or trade.
"""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Dict, Iterable

from .abstention_causality import _rows, _dt
from .decision_outcome_attribution import DEFAULT_DB, _availability

VERSION = "69.10.31"
SCHEMA_VERSION = "apex.counterfactual_cluster_discrimination.v1"


def _cluster_id(label: str, ticker: str, direction: str, anchor: str) -> str:
    raw=f"{label}|{ticker}|{direction}|{anchor}".encode()
    return "ccd_"+hashlib.sha256(raw).hexdigest()[:20]


def _label(row: Dict[str, Any]) -> str | None:
    if bool(row.get("missed_opportunity")): return "MISSED_OPPORTUNITY"
    if bool(row.get("protective_abstention")): return "PROTECTIVE_ABSTENTION"
    return None


def _time_bucket(value: str) -> str:
    d=_dt(value).astimezone(ZoneInfo("America/New_York")); minutes=d.hour*60+d.minute
    if minutes < 570: return "BEFORE_0930_ET"
    if minutes < 600: return "0930_1000_ET"
    if minutes < 660: return "1000_1100_ET"
    if minutes < 690: return "1100_1130_ET"
    if minutes < 780: return "1130_1300_ET"
    return "AFTER_1300_ET"


def _confidence_bucket(v: float) -> str:
    if v < 60: return "LT60"
    if v < 70: return "60_69"
    if v < 80: return "70_79"
    if v < 90: return "80_89"
    return "GE90"


def _cluster_rows(rows: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
    clusters=[]; active={}
    for r in rows:
        label=_label(r)
        if not label: continue
        key=(label,str(r.get("ticker") or ""),str(r.get("direction") or "").upper())
        when=_dt(str(r["captured_at"])); horizon=int(r.get("horizon_seconds") or 300)
        c=active.get(key)
        if c is None or (when-c["_anchor_dt"]).total_seconds()>int(c["horizon_seconds"]):
            c={"cluster_id":_cluster_id(label,key[1],key[2],str(r["captured_at"])),
               "classification":label,"ticker":key[1],"direction":key[2],"anchor_at":str(r["captured_at"]),
               "last_at":str(r["captured_at"]),"horizon_seconds":horizon,"observations":0,"decision_ids":[],
               "confidence_sum":0.0,"confidence_first":None,"confidence_last":None,"confidence_min":None,"confidence_max":None,
               "families":Counter(),"authoritative_families":Counter(),"max_mfe":None,"worst_mae":None,"max_directional_move":None,
               "_anchor_dt":when}
            active[key]=c; clusters.append(c)
        conf=float(r.get("confidence") or 0.0)
        c["last_at"]=str(r["captured_at"]); c["observations"]+=1; c["decision_ids"].append(str(r["decision_id"])); c["confidence_sum"]+=conf
        if c["confidence_first"] is None: c["confidence_first"]=conf
        c["confidence_last"]=conf
        c["confidence_min"]=conf if c["confidence_min"] is None else min(c["confidence_min"],conf)
        c["confidence_max"]=conf if c["confidence_max"] is None else max(c["confidence_max"],conf)
        for fam,detail in r.get("causality",{}).get("families",{}).items():
            c["families"][fam]+=1
            if detail.get("authoritative_block"): c["authoritative_families"][fam]+=1
        for src,dst,mode in (("mfe","max_mfe","max"),("mae","worst_mae","min"),("directional_move","max_directional_move","max")):
            v=r.get(src)
            if v is None: continue
            v=float(v); old=c[dst]
            c[dst]=v if old is None else (max(old,v) if mode=="max" else min(old,v))
    out=[]
    for c in clusters:
        x={k:v for k,v in c.items() if not k.startswith("_") and k!="confidence_sum"}
        x["avg_confidence"]=round(c["confidence_sum"]/c["observations"],2)
        x["confidence_delta"]=round(float(c["confidence_last"])-float(c["confidence_first"]),2)
        x["duration_seconds"]=round((_dt(c["last_at"])-_dt(c["anchor_at"])).total_seconds(),3)
        x["time_bucket"]=_time_bucket(c["anchor_at"])
        x["confidence_bucket"]=_confidence_bucket(x["avg_confidence"])
        x["persistence_bucket"]="GE3" if c["observations"]>=3 else ("TWO" if c["observations"]==2 else "ONE")
        x["families"]=dict(sorted(c["families"].items())); x["authoritative_families"]=dict(sorted(c["authoritative_families"].items()))
        x["capability_signature"]="+".join(sorted(c["families"])) or "NONE"
        out.append(x)
    return out


def clusters(path: str|Path=DEFAULT_DB) -> list[Dict[str,Any]]:
    return _cluster_rows(_rows(path))


def _dimension(clusters_: list[Dict[str,Any]], getter) -> list[Dict[str,Any]]:
    bins=defaultdict(lambda:{"missed_clusters":0,"protective_clusters":0})
    for c in clusters_:
        values=getter(c); values=values if isinstance(values,(list,tuple,set)) else [values]
        for value in values:
            b=bins[str(value)]
            if c["classification"]=="MISSED_OPPORTUNITY": b["missed_clusters"]+=1
            else: b["protective_clusters"]+=1
    total_m=sum(c["classification"]=="MISSED_OPPORTUNITY" for c in clusters_); total=len(clusters_)
    baseline=(total_m/total) if total else 0.0
    out=[]
    for value,b in bins.items():
        n=b["missed_clusters"]+b["protective_clusters"]; rate=b["missed_clusters"]/n if n else 0.0
        out.append({"value":value,**b,"clusters":n,"missed_rate_pct":round(rate*100,2),
                    "baseline_missed_rate_pct":round(baseline*100,2),
                    "relative_risk_vs_baseline":round(rate/baseline,3) if baseline else None,
                    "risk_difference_pct_points":round((rate-baseline)*100,2)})
    return sorted(out,key=lambda x:(x["missed_rate_pct"],x["clusters"]),reverse=True)


def _excursion_semantics(rows: list[Dict[str,Any]]) -> Dict[str,Any]:
    mfe_bad=sum(1 for r in rows if r.get("mfe") is not None and float(r["mfe"])<0)
    # Canonical direction-adjusted adverse excursion is expected <= 0. Positive
    # values are flagged, not repaired or reinterpreted.
    mae_positive=sum(1 for r in rows if r.get("mae") is not None and float(r["mae"])>0)
    return {"status":"INCONSISTENT" if (mfe_bad or mae_positive) else "CONSISTENT",
            "rows_checked":len(rows),"negative_mfe_rows":mfe_bad,"positive_mae_rows":mae_positive,
            "excursions_eligible_as_discriminators":False,
            "reason":"post-outcome excursion is never a decision-time discriminator; sign inconsistencies are reported without repair"}


def summary(path: str|Path=DEFAULT_DB) -> Dict[str,Any]:
    av=_availability(path); base={"ok":not av.get("degraded",False),"version":VERSION,"schema_version":SCHEMA_VERSION,**av,"execution_authority":False}
    if av.get("status")!="READY": return {**base,"cluster_counts":{},"dimensions":{}}
    rows=_rows(path); cs=_cluster_rows(rows)
    missed=sum(c["classification"]=="MISSED_OPPORTUNITY" for c in cs); protective=len(cs)-missed
    dims={
      "time_of_day":_dimension(cs,lambda c:c["time_bucket"]),
      "direction":_dimension(cs,lambda c:c["direction"]),
      "persistence":_dimension(cs,lambda c:c["persistence_bucket"]),
      "confidence":_dimension(cs,lambda c:c["confidence_bucket"]),
      "capability_signature":_dimension(cs,lambda c:c["capability_signature"]),
      "canonical_family_presence":_dimension(cs,lambda c:list(c["families"].keys())),
    }
    return {**base,"status":"READY","cluster_counts":{"total":len(cs),"missed":missed,"protective":protective,
             "baseline_missed_rate_pct":round(100*missed/len(cs),2) if cs else None},
            "dimensions":dims,"excursion_semantics":_excursion_semantics(rows),
            "governance":{"observational_only":True,"decision_time_features_only_for_discrimination":True,
             "outcome_excursions_excluded_from_discriminators":True,"changes_trade_decisions":False,"changes_thresholds":False,
             "changes_learning_eligibility":False,"feeds_calibration_automatically":False,"changes_execution_authority":False,
             "automatic_promotion":False,"human_review_required_for_policy_change":True,
             "cluster_deduplication_is_analytical_only":True,"cohort_timezone_rule":"America/New_York via zoneinfo"}}


def cluster_detail(path: str|Path=DEFAULT_DB,limit:int=500,classification:str|None=None)->Dict[str,Any]:
    av=_availability(path)
    if av.get("status")!="READY": return {"ok":not av.get("degraded",False),"version":VERSION,**av,"items":[]}
    items=list(reversed(clusters(path))); cls=str(classification or "").upper()
    if cls in {"MISSED","MISSED_OPPORTUNITY"}: items=[x for x in items if x["classification"]=="MISSED_OPPORTUNITY"]
    elif cls in {"PROTECTIVE","PROTECTIVE_ABSTENTION"}: items=[x for x in items if x["classification"]=="PROTECTIVE_ABSTENTION"]
    return {"ok":True,"version":VERSION,"schema_version":SCHEMA_VERSION,**av,"items":items[:max(1,min(int(limit),2000))],"execution_authority":False}
