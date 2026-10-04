"""APEX 69.10.33 — Open Discovery Counterfactual Discrimination & Shadow Eligibility.

Read-only research surface over immutable counterfactual abstention clusters.  It
restricts analysis to canonical RTH OPEN_DISCOVERY (09:30-10:00 ET), derives
features exclusively from decision-time evidence already frozen on attribution
rows, and evaluates candidate signatures with chronological date holdout.

SHADOW_ELIGIBLE_CANDIDATE is an analytical label only. It never changes the
canonical NO_TRADE decision, thresholds, learning eligibility, calibration, or
execution authority.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

from .abstention_causality import _rows, _dt
from .canonical_market_calendar import classify as classify_market_session
from .decision_outcome_attribution import DEFAULT_DB, _availability

VERSION = "69.10.33"
SCHEMA_VERSION = "apex.open_discovery_shadow_eligibility.v1"
MIN_TRAIN_SUPPORT = 6
MIN_HOLDOUT_SUPPORT = 3
MIN_TRAIN_MISSED = 2
MIN_LIFT = 1.25


def _classification(row: Mapping[str, Any]) -> str | None:
    if bool(row.get("missed_opportunity")): return "MISSED_OPPORTUNITY"
    if bool(row.get("protective_abstention")): return "PROTECTIVE_ABSTENTION"
    return None


def _conf_bucket(v: float) -> str:
    if v < 60: return "LT60"
    if v < 70: return "60_69"
    if v < 80: return "70_79"
    if v < 90: return "80_89"
    return "GE90"


def _state_signature(row: Mapping[str, Any]) -> str:
    """Stable decision-time contributor-state signature; never uses outcomes."""
    parts=[]
    for family, detail in sorted((row.get("causality") or {}).get("families", {}).items()):
        states=detail.get("contributor_states") or {}
        if states:
            parts.append(f"{family}=" + "+".join(sorted(str(s) for s in states)))
    return "|".join(parts) or "NONE"


def _open_discovery_rows(path: str|Path=DEFAULT_DB) -> list[Dict[str,Any]]:
    out=[]
    for r in _rows(path):
        if not _classification(r): continue
        cal=classify_market_session(str(r.get("captured_at")))
        if not cal.get("rth_eligible") or cal.get("session_phase") != "OPEN_DISCOVERY": continue
        x=dict(r); x["classification"]=_classification(r); x["calendar"]=cal
        x["confidence_bucket"]=_conf_bucket(float(r.get("confidence") or 0.0))
        x["state_signature"]=_state_signature(r)
        x["family_signature"]="+".join(sorted((r.get("causality") or {}).get("families",{}))) or "NONE"
        out.append(x)
    return out


def _cluster_rows(rows: Iterable[Dict[str,Any]]) -> list[Dict[str,Any]]:
    """Same anchor-horizon analytical dedup rule as 69.10.31, now RTH-open only."""
    clusters=[]; active={}
    for r in rows:
        label=r["classification"]; key=(label,str(r.get("ticker") or ""),str(r.get("direction") or "").upper())
        when=_dt(str(r["captured_at"])); horizon=int(r.get("horizon_seconds") or 300); c=active.get(key)
        if c is None or (when-c["_anchor_dt"]).total_seconds()>int(c["horizon_seconds"]):
            c={"classification":label,"ticker":key[1],"direction":key[2],"anchor_at":str(r["captured_at"]),
               "last_at":str(r["captured_at"]),"horizon_seconds":horizon,"observations":0,"decision_ids":[],
               "confidence_sum":0.0,"confidence_first":None,"confidence_last":None,"families":Counter(),
               "states":Counter(),"_anchor_dt":when}
            active[key]=c; clusters.append(c)
        conf=float(r.get("confidence") or 0.0); c["observations"]+=1; c["decision_ids"].append(str(r.get("decision_id")))
        c["last_at"]=str(r["captured_at"]); c["confidence_sum"]+=conf
        if c["confidence_first"] is None: c["confidence_first"]=conf
        c["confidence_last"]=conf
        for fam,detail in (r.get("causality") or {}).get("families",{}).items():
            c["families"][fam]+=1
            for state in (detail.get("contributor_states") or {}): c["states"][f"{fam}:{state}"]+=1
    result=[]
    for c in clusters:
        avg=c["confidence_sum"]/c["observations"] if c["observations"] else 0.0
        x={k:v for k,v in c.items() if not k.startswith("_") and k!="confidence_sum"}
        x["avg_confidence"]=round(avg,2); x["confidence_bucket"]=_conf_bucket(avg)
        x["confidence_delta"]=round(float(c["confidence_last"])-float(c["confidence_first"]),2)
        x["confidence_trajectory"]="RISING" if x["confidence_delta"]>1 else ("FALLING" if x["confidence_delta"]<-1 else "STABLE")
        x["persistence_bucket"]="GE3" if c["observations"]>=3 else ("TWO" if c["observations"]==2 else "ONE")
        x["family_signature"]="+".join(sorted(c["families"])) or "NONE"
        x["state_signature"]="|".join(sorted(c["states"])) or "NONE"
        x["session_date_et"]=str(classify_market_session(c["anchor_at"])["session_date"])
        result.append(x)
    return result


def clusters(path: str|Path=DEFAULT_DB) -> list[Dict[str,Any]]:
    return _cluster_rows(_open_discovery_rows(path))


def _rate(items: list[Dict[str,Any]]) -> float:
    return sum(x["classification"]=="MISSED_OPPORTUNITY" for x in items)/len(items) if items else 0.0


def _chronological_split(cs: list[Dict[str,Any]]) -> tuple[list[Dict[str,Any]],list[Dict[str,Any]],Dict[str,Any]]:
    dates=sorted({c["session_date_et"] for c in cs})
    if len(dates)<2: return cs,[],{"method":"SESSION_DATE_CHRONOLOGICAL","status":"INSUFFICIENT_DATES","train_dates":dates,"holdout_dates":[]}
    cut=max(1,int(len(dates)*0.7)); cut=min(cut,len(dates)-1); train_dates=set(dates[:cut]); holdout_dates=set(dates[cut:])
    return ([c for c in cs if c["session_date_et"] in train_dates], [c for c in cs if c["session_date_et"] in holdout_dates],
            {"method":"SESSION_DATE_CHRONOLOGICAL","status":"READY","train_dates":sorted(train_dates),"holdout_dates":sorted(holdout_dates),"date_split_index":cut})


def _candidate_dimensions(c: Dict[str,Any]) -> Dict[str,str]:
    return {"direction":c["direction"],"confidence_bucket":c["confidence_bucket"],"confidence_trajectory":c["confidence_trajectory"],
            "persistence_bucket":c["persistence_bucket"],"family_signature":c["family_signature"],"state_signature":c["state_signature"]}


def _discover(train: list[Dict[str,Any]], holdout: list[Dict[str,Any]]) -> list[Dict[str,Any]]:
    base_train=_rate(train); base_hold=_rate(holdout); bins=defaultdict(lambda:{"train":[],"holdout":[]})
    for cohort,name in ((train,"train"),(holdout,"holdout")):
        for c in cohort:
            for dim,val in _candidate_dimensions(c).items(): bins[(dim,val)][name].append(c)
    out=[]
    for (dim,val),sets in bins.items():
        tr,ho=sets["train"],sets["holdout"]; tr_rate=_rate(tr); ho_rate=_rate(ho)
        tr_m=sum(x["classification"]=="MISSED_OPPORTUNITY" for x in tr); ho_m=sum(x["classification"]=="MISSED_OPPORTUNITY" for x in ho)
        train_lift=tr_rate/base_train if base_train else None; hold_lift=ho_rate/base_hold if base_hold else None
        support_ok=len(tr)>=MIN_TRAIN_SUPPORT and tr_m>=MIN_TRAIN_MISSED
        holdout_ok=len(ho)>=MIN_HOLDOUT_SUPPORT
        directionally_valid=bool(support_ok and holdout_ok and train_lift is not None and hold_lift is not None and train_lift>=MIN_LIFT and hold_lift>1.0)
        out.append({"feature":dim,"value":val,"train_clusters":len(tr),"train_missed":tr_m,"train_missed_rate_pct":round(tr_rate*100,2),
                    "train_lift_vs_baseline":round(train_lift,3) if train_lift is not None else None,
                    "holdout_clusters":len(ho),"holdout_missed":ho_m,"holdout_missed_rate_pct":round(ho_rate*100,2) if ho else None,
                    "holdout_lift_vs_baseline":round(hold_lift,3) if hold_lift is not None else None,
                    "minimum_support_pass":support_ok,"holdout_support_pass":holdout_ok,"chronological_validation_pass":directionally_valid,
                    "shadow_status":"SHADOW_ELIGIBLE_CANDIDATE" if directionally_valid else "NOT_PROMOTED"})
    return sorted(out,key=lambda x:(x["chronological_validation_pass"],x["train_lift_vs_baseline"] or 0,x["train_clusters"]),reverse=True)


def summary(path: str|Path=DEFAULT_DB) -> Dict[str,Any]:
    av=_availability(path); base={"ok":not av.get("degraded",False),"version":VERSION,"schema_version":SCHEMA_VERSION,**av,"execution_authority":False}
    if av.get("status")!="READY": return {**base,"population":{},"validation":{},"candidates":[]}
    cs=clusters(path); train,hold,split=_chronological_split(cs); candidates=_discover(train,hold) if hold else []
    missed=sum(c["classification"]=="MISSED_OPPORTUNITY" for c in cs); protective=len(cs)-missed
    available=Counter();
    for c in cs:
        for k,v in _candidate_dimensions(c).items():
            if v and v!="NONE": available[k]+=1
    promoted=sum(x["chronological_validation_pass"] for x in candidates)
    return {**base,"status":"READY","population":{"scope":"RTH_OPEN_DISCOVERY_0930_1000_ET","clusters":len(cs),"missed_clusters":missed,
             "protective_clusters":protective,"missed_rate_pct":round(100*missed/len(cs),2) if cs else None},
            "decision_time_feature_coverage":dict(sorted(available.items())),
            "unavailable_feature_note":"Only evidence frozen in decision_effectiveness_attribution is analyzed; structural-map fields absent from that immutable row are reported as unavailable rather than reconstructed.",
            "validation":{**split,"train_clusters":len(train),"train_missed_rate_pct":round(_rate(train)*100,2) if train else None,
                          "holdout_clusters":len(hold),"holdout_missed_rate_pct":round(_rate(hold)*100,2) if hold else None,
                          "minimum_train_support":MIN_TRAIN_SUPPORT,"minimum_holdout_support":MIN_HOLDOUT_SUPPORT,"minimum_train_missed":MIN_TRAIN_MISSED,"minimum_train_lift":MIN_LIFT},
            "candidates":candidates,"shadow_eligible_candidate_count":promoted,
            "governance":{"observational_only":True,"canonical_no_trade_unchanged":True,"shadow_label_has_no_decision_authority":True,
              "decision_time_features_only":True,"outcome_excursions_excluded":True,"chronological_session_date_holdout_required":True,
              "structural_fields_not_reconstructed":True,"changes_trade_decisions":False,"changes_thresholds":False,
              "changes_learning_eligibility":False,"feeds_calibration_automatically":False,"automatic_promotion":False,
              "automatic_execution":False,"automatic_order_submission":False,"human_review_required_for_policy_change":True}}


def detail(path: str|Path=DEFAULT_DB,limit:int=500,classification:str|None=None)->Dict[str,Any]:
    av=_availability(path)
    if av.get("status")!="READY": return {"ok":not av.get("degraded",False),"version":VERSION,**av,"items":[]}
    items=list(reversed(clusters(path))); cls=str(classification or "").upper()
    if cls in {"MISSED","MISSED_OPPORTUNITY"}: items=[x for x in items if x["classification"]=="MISSED_OPPORTUNITY"]
    elif cls in {"PROTECTIVE","PROTECTIVE_ABSTENTION"}: items=[x for x in items if x["classification"]=="PROTECTIVE_ABSTENTION"]
    # Explicitly omit outcome excursion fields: this is a decision-time research surface.
    return {"ok":True,"version":VERSION,"schema_version":SCHEMA_VERSION,**av,"items":items[:max(1,min(int(limit),2000))],"execution_authority":False}
