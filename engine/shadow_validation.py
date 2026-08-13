"""APEX 13 Sprint 8: governed shadow validation and promotion review.

Research-only. This module never mutates production configuration or live recommendations.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, math, sqlite3, uuid
from typing import Any, Dict, Mapping, Optional, List
from . import institutional_governance as gov

VERSION="13.0.8"
SCHEMA_VERSION="apex.shadow.validation.v1"
DEFAULT_REQUIRED_SESSIONS=10
DEFAULT_REQUIRED_RECOMMENDATIONS=50
DEFAULT_MAX_DIVERGENCE=0.35


def _now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def _json(v): return json.dumps(v,sort_keys=True,separators=(",",":"),default=str)
def _load(v, default=None):
    if v in (None,""): return {} if default is None else default
    try:return json.loads(v)
    except Exception:return {} if default is None else default

def _conn():
    c=sqlite3.connect(gov.DB_PATH); c.row_factory=sqlite3.Row; c.execute("PRAGMA foreign_keys=ON"); return c

def init_db():
    gov.init_db()
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS shadow_campaigns(
          campaign_id TEXT PRIMARY KEY,candidate_id TEXT NOT NULL,champion_version TEXT NOT NULL,status TEXT NOT NULL,
          created_at TEXT NOT NULL,started_at TEXT,ended_at TEXT,required_sessions INTEGER NOT NULL,
          required_recommendations INTEGER NOT NULL,max_duration_days INTEGER NOT NULL,required_regimes_json TEXT NOT NULL,
          gate_config_json TEXT NOT NULL,feature_version TEXT,dataset_hash TEXT,kill_switch_reason TEXT,metadata_json TEXT NOT NULL,
          FOREIGN KEY(candidate_id) REFERENCES model_registry(candidate_id));
        CREATE INDEX IF NOT EXISTS idx_campaign_candidate ON shadow_campaigns(candidate_id,created_at);
        CREATE TABLE IF NOT EXISTS shadow_campaign_observations(
          observation_id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL,recommendation_id TEXT NOT NULL,observed_at TEXT NOT NULL,
          session_date TEXT NOT NULL,regime TEXT,strategy_family TEXT,evidence_id TEXT,data_quality TEXT NOT NULL,
          production_json TEXT NOT NULL,candidate_json TEXT NOT NULL,comparison_json TEXT NOT NULL,
          outcome_label TEXT,outcome_json TEXT NOT NULL,integrity_hash TEXT NOT NULL,
          FOREIGN KEY(campaign_id) REFERENCES shadow_campaigns(campaign_id));
        CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_rec_unique ON shadow_campaign_observations(campaign_id,recommendation_id);
        CREATE INDEX IF NOT EXISTS idx_campaign_obs_time ON shadow_campaign_observations(campaign_id,observed_at);
        CREATE TABLE IF NOT EXISTS promotion_review_packages(
          package_id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL,candidate_id TEXT NOT NULL,created_at TEXT NOT NULL,
          disposition TEXT NOT NULL,summary_json TEXT NOT NULL,gates_json TEXT NOT NULL,coverage_json TEXT NOT NULL,
          scorecard_json TEXT NOT NULL,limitations_json TEXT NOT NULL,integrity_hash TEXT NOT NULL,status TEXT NOT NULL,
          FOREIGN KEY(campaign_id) REFERENCES shadow_campaigns(campaign_id));
        CREATE UNIQUE INDEX IF NOT EXISTS idx_review_campaign ON promotion_review_packages(campaign_id);
        CREATE TABLE IF NOT EXISTS champion_registry(
          domain TEXT PRIMARY KEY,champion_version TEXT NOT NULL,candidate_id TEXT,updated_at TEXT NOT NULL,updated_by TEXT NOT NULL,
          metadata_json TEXT NOT NULL);
        """)
    return {"ok":True,"schema_version":SCHEMA_VERSION}

def _candidate(cid): return gov.candidates(cid)
def _campaign(cid):
    init_db()
    with _conn() as c:r=c.execute("SELECT * FROM shadow_campaigns WHERE campaign_id=?",(cid,)).fetchone()
    return _decode_campaign(r) if r else None

def _decode_campaign(r):
    d=dict(r); d["required_regimes"]=_load(d.pop("required_regimes_json"),[]); d["gate_config"]=_load(d.pop("gate_config_json"),{}); d["metadata"]=_load(d.pop("metadata_json"),{}); return d

def create_campaign(candidate_id:str,payload:Mapping[str,Any],actor="API"):
    init_db(); cand=_candidate(candidate_id)
    if not cand:return {"ok":False,"status":"UNAVAILABLE","error":"candidate not found"}
    if cand["status"]!="SHADOW_ONLY":return {"ok":False,"status":"APPROVAL_REQUIRED","error":"candidate must be approved for shadow mode"}
    cid=str(uuid.uuid4()); champion=str(payload.get("champion_version") or cand.get("baseline_version") or "PRODUCTION_CURRENT")
    gates={"max_divergence_rate":float(payload.get("max_divergence_rate",DEFAULT_MAX_DIVERGENCE)),"minimum_accuracy_delta":float(payload.get("minimum_accuracy_delta",-0.02)),"maximum_brier_delta":float(payload.get("maximum_brier_delta",0.02)),"minimum_good_quality_rate":float(payload.get("minimum_good_quality_rate",0.8))}
    with _conn() as c:c.execute("INSERT INTO shadow_campaigns VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(cid,candidate_id,champion,"PENDING",_now(),None,None,int(payload.get("required_sessions",DEFAULT_REQUIRED_SESSIONS)),int(payload.get("required_recommendations",DEFAULT_REQUIRED_RECOMMENDATIONS)),int(payload.get("max_duration_days",45)),_json(payload.get("required_regimes") or []),_json(gates),payload.get("feature_version"),payload.get("dataset_hash"),None,_json({"production_effect":"NONE","created_by":actor})))
    gov.audit("CREATE_SHADOW_CAMPAIGN","shadow_campaign",cid,new={"candidate_id":candidate_id,"champion_version":champion},actor=actor)
    return {"ok":True,"status":"PENDING","campaign_id":cid,"production_effect":"NONE"}

def transition(campaign_id:str,action:str,actor="API",reason=""):
    cur=_campaign(campaign_id)
    if not cur:return {"ok":False,"status":"UNAVAILABLE","error":"campaign not found"}
    maps={"start":({"PENDING","PAUSED"},"ACTIVE"),"pause":({"ACTIVE"},"PAUSED"),"resume":({"PAUSED"},"ACTIVE"),"terminate":({"PENDING","ACTIVE","PAUSED","INSUFFICIENT_COVERAGE"},"FAILED")}
    if action not in maps:return {"ok":False,"status":"UNAVAILABLE","error":"invalid action"}
    allowed,new=maps[action]
    if cur["status"] not in allowed:return {"ok":False,"status":"APPROVAL_REQUIRED","error":f"cannot {action} from {cur['status']}"}
    started=cur["started_at"] or (_now() if new=="ACTIVE" else None); ended=_now() if new=="FAILED" else cur["ended_at"]
    with _conn() as c:c.execute("UPDATE shadow_campaigns SET status=?,started_at=?,ended_at=?,kill_switch_reason=? WHERE campaign_id=?",(new,started,ended,reason if new=="FAILED" else cur.get("kill_switch_reason"),campaign_id))
    gov.audit(action.upper(),"shadow_campaign",campaign_id,previous={"status":cur["status"]},new={"status":new},explanation=reason,actor=actor)
    return {"ok":True,"status":new,"campaign_id":campaign_id,"production_effect":"NONE"}

def record_observation(campaign_id:str,payload:Mapping[str,Any],actor="SYSTEM"):
    cur=_campaign(campaign_id)
    if not cur:return {"ok":False,"status":"UNAVAILABLE","error":"campaign not found"}
    if cur["status"]!="ACTIVE":return {"ok":False,"status":"DISABLED","error":"campaign is not ACTIVE"}
    rid=str(payload.get("recommendation_id") or "").strip()
    if not rid:return {"ok":False,"status":"UNAVAILABLE","error":"recommendation_id required"}
    prod=payload.get("production") or {}; cand=payload.get("candidate") or {}; comp=payload.get("comparison") or {}
    if not isinstance(prod,dict) or not isinstance(cand,dict):return kill_switch(campaign_id,"INVALID_OUTPUT",actor)
    at=str(payload.get("observed_at") or _now()); session=str(payload.get("session_date") or at[:10]); quality=str(payload.get("data_quality") or "UNKNOWN").upper()
    body={"campaign_id":campaign_id,"recommendation_id":rid,"observed_at":at,"production":prod,"candidate":cand,"comparison":comp}
    h=hashlib.sha256(_json(body).encode()).hexdigest(); oid=str(uuid.uuid4())
    try:
        with _conn() as c:c.execute("INSERT INTO shadow_campaign_observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(oid,campaign_id,rid,at,session,payload.get("regime"),payload.get("strategy_family"),payload.get("evidence_id"),quality,_json(prod),_json(cand),_json(comp),payload.get("outcome_label"),_json(payload.get("outcome") or {}),h))
    except sqlite3.IntegrityError:return {"ok":False,"status":"APPROVAL_REQUIRED","error":"duplicate campaign recommendation"}
    gov.audit("SHADOW_CAMPAIGN_OBSERVATION","shadow_campaign",campaign_id,new={"observation_id":oid,"recommendation_id":rid},actor=actor)
    gates=gate_results(campaign_id)
    if gates.get("kill_switch"):
        kill_switch(campaign_id,gates["kill_switch"],actor)
    return {"ok":True,"status":"SHADOW_ONLY","observation_id":oid,"campaign_id":campaign_id,"production_changed":False}

def observations(campaign_id:str,limit=500):
    init_db()
    with _conn() as c:rows=c.execute("SELECT * FROM shadow_campaign_observations WHERE campaign_id=? ORDER BY observed_at ASC LIMIT ?",(campaign_id,max(1,min(limit,5000)))).fetchall()
    out=[]
    for r in rows:
        d=dict(r); d["production"]=_load(d.pop("production_json")); d["candidate"]=_load(d.pop("candidate_json")); d["comparison"]=_load(d.pop("comparison_json")); d["outcome"]=_load(d.pop("outcome_json")); out.append(d)
    return out

def _prob(d):
    for k in ("score","confidence","probability"):
        try:
            if d.get(k) is not None:
                v=float(d[k]); return max(0,min(1,v/100 if v>1 else v))
        except Exception:pass
    return None

def _label(o):
    x=str(o.get("outcome_label") or "").upper(); return 1 if x in {"WIN","CORRECT","PROFIT","1","TRUE"} else (0 if x in {"LOSS","INCORRECT","0","FALSE"} else None)

def scorecard(campaign_id:str):
    cur=_campaign(campaign_id)
    if not cur:return {"status":"UNAVAILABLE","error":"campaign not found"}
    rows=observations(campaign_id); graded=[r for r in rows if _label(r) is not None]
    def metrics(which):
        pairs=[(_prob(r[which]),_label(r)) for r in graded]; pairs=[p for p in pairs if p[0] is not None]
        if not pairs:return {"sample_size":0,"accuracy":None,"brier":None,"log_loss":None}
        acc=sum((p>=.5)==bool(y) for p,y in pairs)/len(pairs); b=sum((p-y)**2 for p,y in pairs)/len(pairs); ll=-sum(y*math.log(max(p,1e-9))+(1-y)*math.log(max(1-p,1e-9)) for p,y in pairs)/len(pairs)
        return {"sample_size":len(pairs),"accuracy":round(acc,6),"brier":round(b,6),"log_loss":round(ll,6)}
    disagreements=sum(1 for r in rows if str(r["production"].get("recommendation"))!=str(r["candidate"].get("recommendation")))
    prod=metrics("production"); cand=metrics("candidate")
    return {"schema_version":"apex.shadow.scorecard.v1","status":"READY" if rows else "COLLECTING","campaign_id":campaign_id,"observation_count":len(rows),"graded_count":len(graded),"agreement_rate":round(1-disagreements/len(rows),6) if rows else None,"disagreement_rate":round(disagreements/len(rows),6) if rows else None,"production":prod,"candidate":cand,"comparison":{"accuracy_delta":None if prod["accuracy"] is None or cand["accuracy"] is None else round(cand["accuracy"]-prod["accuracy"],6),"brier_delta":None if prod["brier"] is None or cand["brier"] is None else round(cand["brier"]-prod["brier"],6)},"limitations":["Descriptive shadow evidence only","Small samples are not conclusive","No production effect"]}

def coverage(campaign_id:str):
    cur=_campaign(campaign_id); rows=observations(campaign_id)
    if not cur:return {"status":"UNAVAILABLE"}
    sessions=sorted({r["session_date"] for r in rows}); regimes=sorted({r["regime"] for r in rows if r.get("regime")}); required=set(cur["required_regimes"])
    return {"status":"READY" if rows else "COLLECTING","campaign_id":campaign_id,"recommendations":{"collected":len(rows),"required":cur["required_recommendations"],"remaining":max(0,cur["required_recommendations"]-len(rows))},"sessions":{"collected":len(sessions),"required":cur["required_sessions"],"remaining":max(0,cur["required_sessions"]-len(sessions))},"regimes":{"observed":regimes,"required":sorted(required),"missing":sorted(required-set(regimes))},"complete":len(rows)>=cur["required_recommendations"] and len(sessions)>=cur["required_sessions"] and not (required-set(regimes))}

def gate_results(campaign_id:str):
    cur=_campaign(campaign_id); sc=scorecard(campaign_id); cov=coverage(campaign_id)
    if not cur:return {"status":"UNAVAILABLE"}
    cfg=cur["gate_config"]; rows=observations(campaign_id); good=sum(1 for r in rows if r["data_quality"] in {"GOOD","VERIFIED"}); quality_rate=good/len(rows) if rows else 0
    checks={"coverage_complete":cov.get("complete",False),"divergence_acceptable":sc.get("disagreement_rate") is None or sc["disagreement_rate"]<=cfg["max_divergence_rate"],"accuracy_non_inferior":sc["comparison"]["accuracy_delta"] is None or sc["comparison"]["accuracy_delta"]>=cfg["minimum_accuracy_delta"],"brier_non_inferior":sc["comparison"]["brier_delta"] is None or sc["comparison"]["brier_delta"]<=cfg["maximum_brier_delta"],"data_quality_acceptable":quality_rate>=cfg["minimum_good_quality_rate"] if rows else False}
    kill=None
    if rows and not checks["divergence_acceptable"]:kill="EXCESSIVE_DIVERGENCE"
    return {"status":"READY" if all(checks.values()) else "INSUFFICIENT_COVERAGE","campaign_id":campaign_id,"checks":checks,"passed":all(checks.values()),"quality_rate":round(quality_rate,6),"kill_switch":kill,"config":cfg}

def kill_switch(campaign_id:str,reason:str,actor="SYSTEM"):
    cur=_campaign(campaign_id)
    if not cur:return {"ok":False,"status":"UNAVAILABLE"}
    with _conn() as c:c.execute("UPDATE shadow_campaigns SET status='PAUSED',kill_switch_reason=? WHERE campaign_id=?",(reason,campaign_id))
    gov.audit("SHADOW_KILL_SWITCH","shadow_campaign",campaign_id,previous={"status":cur["status"]},new={"status":"PAUSED","reason":reason},actor=actor)
    return {"ok":True,"status":"PAUSED","campaign_id":campaign_id,"kill_switch_reason":reason,"production_effect":"NONE"}

def finalize(campaign_id:str,actor="API"):
    cur=_campaign(campaign_id)
    if not cur:return {"ok":False,"status":"UNAVAILABLE","error":"campaign not found"}
    gates=gate_results(campaign_id); cov=coverage(campaign_id); sc=scorecard(campaign_id)
    disposition="ELIGIBLE_FOR_PRODUCTION_REVIEW" if gates.get("passed") else ("CONTINUE_SHADOW" if not cov.get("complete") else "REVISE_CANDIDATE")
    summary={"candidate_id":cur["candidate_id"],"champion_version":cur["champion_version"],"production_effect":"NONE","recommended_disposition":disposition}
    h=hashlib.sha256(_json({"summary":summary,"gates":gates,"coverage":cov,"scorecard":sc}).encode()).hexdigest(); pid=str(uuid.uuid4())
    try:
        with _conn() as c:
            c.execute("INSERT INTO promotion_review_packages VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(pid,campaign_id,cur["candidate_id"],_now(),disposition,_json(summary),_json(gates),_json(cov),_json(sc),_json(["Human review required","No automatic production promotion"]),h,"READY_FOR_REVIEW"))
            c.execute("UPDATE shadow_campaigns SET status=?,ended_at=? WHERE campaign_id=?",("READY_FOR_REVIEW" if disposition=="ELIGIBLE_FOR_PRODUCTION_REVIEW" else "COMPLETED",_now(),campaign_id))
    except sqlite3.IntegrityError:
        with _conn() as c:r=c.execute("SELECT package_id FROM promotion_review_packages WHERE campaign_id=?",(campaign_id,)).fetchone()
        return {"ok":True,"status":"READY_FOR_REVIEW","package_id":r["package_id"],"disposition":disposition,"deduplicated":True,"production_effect":"NONE"}
    gov.audit("FINALIZE_SHADOW_CAMPAIGN","shadow_campaign",campaign_id,new={"package_id":pid,"disposition":disposition},actor=actor)
    return {"ok":True,"status":"READY_FOR_REVIEW","package_id":pid,"disposition":disposition,"production_effect":"NONE"}

def campaigns(limit=100):
    init_db()
    with _conn() as c:rows=c.execute("SELECT * FROM shadow_campaigns ORDER BY created_at DESC LIMIT ?",(max(1,min(limit,500)),)).fetchall()
    return [_decode_campaign(r) for r in rows]

def packages(limit=100):
    init_db()
    with _conn() as c:rows=c.execute("SELECT * FROM promotion_review_packages ORDER BY created_at DESC LIMIT ?",(max(1,min(limit,500)),)).fetchall()
    out=[]
    for r in rows:
        d=dict(r)
        for src,dst,default in (("summary_json","summary",{}),("gates_json","gates",{}),("coverage_json","coverage",{}),("scorecard_json","scorecard",{}),("limitations_json","limitations",[])):d[dst]=_load(d.pop(src),default)
        out.append(d)
    return out

def champion_challenger(domain="decision_weights"):
    init_db()
    with _conn() as c:r=c.execute("SELECT * FROM champion_registry WHERE domain=?",(domain,)).fetchone()
    champion=dict(r) if r else {"domain":domain,"champion_version":"PRODUCTION_CURRENT","candidate_id":None,"updated_at":None,"updated_by":"SYSTEM","metadata_json":"{}"}
    champion["metadata"]=_load(champion.pop("metadata_json", "{}")); active=[x for x in campaigns() if x["status"] in {"ACTIVE","PAUSED","READY_FOR_REVIEW"}]
    return {"status":"READY","champion":champion,"challengers":active,"automatic_replacement":False,"production_effect":"NONE"}
