"""APEX 11.4-12.3 governed historical, research, and adaptive control plane.

The module stores evidence and governance metadata only. It never fabricates outcomes,
never queries market-data providers, and never promotes a candidate automatically.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, math, os, sqlite3, uuid
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

VERSION = "13.0.6"
SCHEMA_VERSION = 5
DB_PATH = os.getenv("APEX_GOVERNANCE_DB", os.path.join(os.path.dirname(os.path.dirname(__file__)), "apex_governance.db"))
MIN_GRADED = int(os.getenv("APEX_MIN_GRADED_HISTORY", "50"))
MIN_SIMILAR = int(os.getenv("APEX_MIN_SIMILAR_OUTCOMES", "20"))
ALLOWED_HISTORY = {"COLLECTING","INSUFFICIENT_HISTORY","READY_FOR_CALIBRATION","DEGRADED_HISTORY","CALIBRATED"}
ALLOWED_PUBLIC = {"UNAVAILABLE","DEGRADED","COLLECTING","INSUFFICIENT_HISTORY","READY","DISABLED","SHADOW_ONLY","APPROVAL_REQUIRED"}


def _now() -> str: return dt.datetime.now(dt.timezone.utc).isoformat()
def _json(v: Any) -> str: return json.dumps(v, sort_keys=True, separators=(",",":"), default=str)
def _load(v: Any, default: Any=None) -> Any:
    if v in (None, ""): return {} if default is None else default
    try: return json.loads(v)
    except Exception: return {} if default is None else default

def _conn():
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; c.execute("PRAGMA foreign_keys=ON"); return c

def init_db() -> Dict[str, Any]:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS governance_schema(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS historical_events(
          event_id TEXT PRIMARY KEY, recommendation_id TEXT, event_at TEXT NOT NULL,
          event_type TEXT NOT NULL, payload_json TEXT NOT NULL, provenance_json TEXT NOT NULL,
          schema_version TEXT NOT NULL, build_version TEXT NOT NULL, integrity_hash TEXT NOT NULL,
          created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_hist_rec_time ON historical_events(recommendation_id,event_at);
        CREATE INDEX IF NOT EXISTS idx_hist_type_time ON historical_events(event_type,event_at);
        CREATE TABLE IF NOT EXISTS graded_outcomes(
          recommendation_id TEXT PRIMARY KEY, graded_at TEXT NOT NULL, outcome_label TEXT NOT NULL,
          realized_pnl REAL, realized_r REAL, family TEXT, regime TEXT, confidence REAL, conviction REAL,
          consensus_grade TEXT, data_quality TEXT NOT NULL, source TEXT NOT NULL, payload_json TEXT NOT NULL,
          integrity_hash TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_outcome_grade ON graded_outcomes(graded_at);
        CREATE INDEX IF NOT EXISTS idx_outcome_family ON graded_outcomes(family,graded_at);
        CREATE TABLE IF NOT EXISTS feature_vectors(
          vector_id TEXT PRIMARY KEY, recommendation_id TEXT, observed_at TEXT NOT NULL,
          feature_version TEXT NOT NULL, feature_hash TEXT NOT NULL, regime TEXT, setup TEXT,
          features_json TEXT NOT NULL, provenance_json TEXT NOT NULL, outcome_eligible INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_vector_time ON feature_vectors(observed_at);
        CREATE INDEX IF NOT EXISTS idx_vector_hash ON feature_vectors(feature_hash,feature_version);
        CREATE TABLE IF NOT EXISTS model_registry(
          candidate_id TEXT PRIMARY KEY, candidate_type TEXT NOT NULL, version TEXT NOT NULL,
          status TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL,
          baseline_version TEXT, dataset_hash TEXT, config_json TEXT NOT NULL, metrics_json TEXT NOT NULL,
          limitations_json TEXT NOT NULL, approved_at TEXT, approved_by TEXT, promoted_at TEXT,
          rollback_of TEXT, artifact_uri TEXT);
        CREATE INDEX IF NOT EXISTS idx_model_status ON model_registry(status,created_at);
        CREATE TABLE IF NOT EXISTS shadow_results(
          shadow_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, observed_at TEXT NOT NULL,
          production_json TEXT NOT NULL, candidate_json TEXT NOT NULL, comparison_json TEXT NOT NULL,
          data_quality TEXT NOT NULL, FOREIGN KEY(candidate_id) REFERENCES model_registry(candidate_id));
        CREATE INDEX IF NOT EXISTS idx_shadow_candidate ON shadow_results(candidate_id,observed_at);
        CREATE TABLE IF NOT EXISTS drift_events(
          drift_id TEXT PRIMARY KEY, detected_at TEXT NOT NULL, metric TEXT NOT NULL, severity TEXT NOT NULL,
          production_version TEXT, candidate_id TEXT, evidence_json TEXT NOT NULL, status TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_drift_time ON drift_events(detected_at);
        CREATE TABLE IF NOT EXISTS governance_audit(
          audit_id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
          entity_type TEXT NOT NULL, entity_id TEXT, previous_json TEXT NOT NULL, new_json TEXT NOT NULL,
          explanation TEXT NOT NULL, build_version TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_audit_time ON governance_audit(occurred_at);
        CREATE TABLE IF NOT EXISTS offline_evaluations(
          evaluation_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, created_at TEXT NOT NULL,
          dataset_hash TEXT NOT NULL, methodology_json TEXT NOT NULL, split_manifest_json TEXT NOT NULL,
          baseline_metrics_json TEXT NOT NULL, candidate_metrics_json TEXT NOT NULL, comparison_json TEXT NOT NULL,
          limitations_json TEXT NOT NULL, status TEXT NOT NULL, integrity_hash TEXT NOT NULL,
          FOREIGN KEY(candidate_id) REFERENCES model_registry(candidate_id));
        CREATE INDEX IF NOT EXISTS idx_eval_candidate ON offline_evaluations(candidate_id,created_at);
        CREATE TABLE IF NOT EXISTS candidate_approvals(
          approval_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, decision TEXT NOT NULL, actor TEXT NOT NULL,
          decided_at TEXT NOT NULL, note TEXT NOT NULL, previous_status TEXT NOT NULL, new_status TEXT NOT NULL,
          evidence_json TEXT NOT NULL, FOREIGN KEY(candidate_id) REFERENCES model_registry(candidate_id));
        CREATE INDEX IF NOT EXISTS idx_approval_candidate ON candidate_approvals(candidate_id,decided_at);
        CREATE TABLE IF NOT EXISTS rollback_history(
          rollback_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, actor TEXT NOT NULL, rolled_back_at TEXT NOT NULL,
          previous_status TEXT NOT NULL, restored_version TEXT, reason TEXT NOT NULL, metadata_json TEXT NOT NULL,
          FOREIGN KEY(candidate_id) REFERENCES model_registry(candidate_id));
        CREATE INDEX IF NOT EXISTS idx_rollback_candidate ON rollback_history(candidate_id,rolled_back_at);
        """)
        c.execute("INSERT OR IGNORE INTO governance_schema(version,applied_at) VALUES(?,?)",(SCHEMA_VERSION,_now()))
    return {"ok":True,"schema_version":SCHEMA_VERSION,"db_path":DB_PATH}

def audit(action:str, entity_type:str, entity_id:Optional[str]=None, *, previous:Any=None,new:Any=None, explanation:str="", actor:str="SYSTEM") -> str:
    init_db(); aid=str(uuid.uuid4())
    with _conn() as c: c.execute("INSERT INTO governance_audit VALUES(?,?,?,?,?,?,?,?,?,?)",(aid,_now(),actor,action,entity_type,entity_id,_json(previous or {}),_json(new or {}),explanation,VERSION))
    return aid

def record_historical_event(event_type:str,payload:Mapping[str,Any],*,recommendation_id:Optional[str]=None,event_at:Optional[str]=None,provenance:Optional[Mapping[str,Any]]=None) -> Dict[str,Any]:
    init_db(); event_at=event_at or _now(); body=_json(payload); prov=_json(provenance or {}); h=hashlib.sha256((event_type+event_at+body+prov).encode()).hexdigest(); eid=str(uuid.uuid4())
    with _conn() as c: c.execute("INSERT INTO historical_events VALUES(?,?,?,?,?,?,?,?,?,?)",(eid,recommendation_id,event_at,event_type,body,prov,"apex.history.event.v1",VERSION,h,_now()))
    audit("CAPTURE","historical_event",eid,new={"event_type":event_type,"recommendation_id":recommendation_id})
    return {"event_id":eid,"integrity_hash":h}

def ingest_outcome(contract:Mapping[str,Any]) -> Dict[str,Any]:
    init_db(); rid=str(contract.get("recommendation_id") or "").strip(); label=str(contract.get("outcome_label") or "").strip().upper(); source=str(contract.get("source") or "").strip()
    if not rid or not label or not source: return {"ok":False,"status":"UNAVAILABLE","error":"recommendation_id, outcome_label, and source are required"}
    quality=str(contract.get("data_quality") or "UNKNOWN").upper(); payload=_json(dict(contract)); h=hashlib.sha256(payload.encode()).hexdigest()
    with _conn() as c:
        exists=c.execute("SELECT * FROM graded_outcomes WHERE recommendation_id=?",(rid,)).fetchone()
        if exists: return {"ok":False,"status":"APPROVAL_REQUIRED","error":"immutable outcome already exists"}
        c.execute("INSERT INTO graded_outcomes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(rid,contract.get("graded_at") or _now(),label,contract.get("realized_pnl"),contract.get("realized_r"),contract.get("family"),contract.get("regime"),contract.get("confidence"),contract.get("conviction"),contract.get("consensus_grade"),quality,source,payload,h))
    audit("INGEST_OUTCOME","graded_outcome",rid,new=dict(contract),explanation="Immutable real outcome contract accepted")
    return {"ok":True,"status":"COLLECTING","recommendation_id":rid,"integrity_hash":h}

def history_report(minimum:int=MIN_GRADED) -> Dict[str,Any]:
    init_db()
    with _conn() as c:
        row=c.execute("SELECT COUNT(*) n, MIN(graded_at) first_at, MAX(graded_at) last_at, SUM(CASE WHEN data_quality IN ('GOOD','VERIFIED') THEN 1 ELSE 0 END) good FROM graded_outcomes").fetchone()
        events=c.execute("SELECT COUNT(*) n FROM historical_events").fetchone()["n"]
    n=int(row["n"] or 0); good=int(row["good"] or 0); missing_rate=0.0 if n==0 else round((n-good)/n*100,2)
    if n==0: status="COLLECTING"
    elif missing_rate>25: status="DEGRADED_HISTORY"
    elif n<minimum: status="INSUFFICIENT_HISTORY"
    else: status="READY_FOR_CALIBRATION"
    return {"schema_version":"apex.history.status.v1","status":status,"sample_size":n,"minimum_evidence":minimum,"remaining":max(0,minimum-n),"event_count":events,"date_coverage":{"start":row["first_at"],"end":row["last_at"]},"missing_or_unverified_rate_pct":missing_rate,"eligible":status=="READY_FOR_CALIBRATION","limitations":["Metrics remain disabled until threshold and quality gates pass"] if status!="READY_FOR_CALIBRATION" else [],"build_version":VERSION}

def scorecard() -> Dict[str,Any]:
    r=history_report()
    if not r["eligible"]: return {"status":"INSUFFICIENT_HISTORY","available":False,"sample_size":r["sample_size"],"eligibility":r,"metrics":{},"statistically_insufficient":True}
    with _conn() as c: rows=c.execute("SELECT outcome_label,realized_pnl,realized_r FROM graded_outcomes WHERE data_quality IN ('GOOD','VERIFIED')").fetchall()
    n=len(rows); wins=sum(1 for x in rows if x["outcome_label"] in ("WIN","PROFIT","TARGET")); losses=sum(1 for x in rows if x["outcome_label"] in ("LOSS","STOP")); pnls=[x["realized_pnl"] for x in rows if x["realized_pnl"] is not None]
    return {"status":"READY","available":True,"sample_size":n,"metrics":{"directional_accuracy":round(wins/max(1,wins+losses),4) if wins+losses else None,"expectancy":round(sum(pnls)/len(pnls),4) if pnls else None},"confidence_intervals":"UNAVAILABLE_WITHOUT_CONFIGURED_STATISTICAL_METHOD","statistically_insufficient":False}

def create_vector(features:Mapping[str,Any],*,recommendation_id:Optional[str]=None,observed_at:Optional[str]=None,feature_version:str="apex.features.v1",regime:Optional[str]=None,setup:Optional[str]=None,provenance:Optional[Mapping[str,Any]]=None) -> Dict[str,Any]:
    init_db(); clean={str(k):v for k,v in sorted(features.items()) if isinstance(v,(int,float,str,bool)) or v is None}; encoded=_json(clean); fh=hashlib.sha256((feature_version+encoded).encode()).hexdigest(); vid=str(uuid.uuid4())
    with _conn() as c: c.execute("INSERT INTO feature_vectors VALUES(?,?,?,?,?,?,?,?,?,?,?)",(vid,recommendation_id,observed_at or _now(),feature_version,fh,regime,setup,encoded,_json(provenance or {}),0,_now()))
    return {"vector_id":vid,"feature_hash":fh,"feature_version":feature_version}

def _numeric(features:Mapping[str,Any]) -> Dict[str,float]:
    out={}
    for k,v in features.items():
        try:
            x=float(v)
            if math.isfinite(x): out[str(k)]=x
        except Exception: pass
    return out

def similarity(vector_id:str,top_k:int=10,as_of:Optional[str]=None) -> Dict[str,Any]:
    init_db()
    with _conn() as c:
        base=c.execute("SELECT * FROM feature_vectors WHERE vector_id=?",(vector_id,)).fetchone()
        if not base: return {"status":"UNAVAILABLE","available":False,"reason":"vector not found","matches":[]}
        cutoff=as_of or base["observed_at"]
        rows=c.execute("SELECT * FROM feature_vectors WHERE vector_id<>? AND observed_at<=? AND feature_version=? ORDER BY observed_at DESC LIMIT 500",(vector_id,cutoff,base["feature_version"])).fetchall()
    a=_numeric(_load(base["features_json"])); matches=[]
    for r in rows:
        b=_numeric(_load(r["features_json"])); keys=sorted(set(a)&set(b))
        if not keys: continue
        dist=math.sqrt(sum((a[k]-b[k])**2 for k in keys)/len(keys)); score=round(100/(1+dist),4)
        matches.append({"vector_id":r["vector_id"],"recommendation_id":r["recommendation_id"],"observed_at":r["observed_at"],"similarity_score":score,"shared_features":len(keys),"outcome_analytics_status":"INSUFFICIENT_HISTORY"})
    matches.sort(key=lambda x:(-x["similarity_score"],x["vector_id"]))
    return {"status":"READY" if matches else "COLLECTING","available":bool(matches),"vector_id":vector_id,"feature_version":base["feature_version"],"look_ahead_guard":{"cutoff":cutoff,"enforced":True},"matches":matches[:max(1,min(top_k,100))],"outcome_performance":None,"message":"Outcome analytics disabled until real graded matches meet evidence thresholds."}

def research_status() -> Dict[str,Any]:
    init_db(); h=history_report()
    with _conn() as c: vectors=c.execute("SELECT COUNT(*) FROM feature_vectors").fetchone()[0]
    return {"status":"READY" if vectors else "COLLECTING","vector_count":vectors,"feature_schema":"apex.features.v1","history":h,"strategy_intelligence":"DISABLED" if not h["eligible"] else "RESEARCH_ONLY","automatic_live_changes":False}

def _candidate_version(candidate_type: str, dataset_hash: Optional[str]) -> str:
    seed = f"{candidate_type}|{dataset_hash or 'NO_DATASET'}|{_now()}"
    return f"{candidate_type.lower()}-{hashlib.sha256(seed.encode()).hexdigest()[:12]}"


def readiness_gates() -> Dict[str, Any]:
    h = history_report(MIN_GRADED)
    gates = {
        "real_graded_history": {"passed": bool(h["eligible"]), "current": h["sample_size"], "required": h["minimum_evidence"]},
        "history_quality": {"passed": h["missing_or_unverified_rate_pct"] <= 25, "current_pct": h["missing_or_unverified_rate_pct"], "maximum_pct": 25},
        "human_approval_configured": {"passed": True, "required": True},
        "automatic_promotion_disabled": {"passed": True, "required": True},
        "rollback_available": {"passed": True, "required": True},
    }
    ready = all(v.get("passed") for v in gates.values())
    status = "READY_FOR_OFFLINE_RESEARCH" if ready else ("COLLECTING" if h["sample_size"] == 0 else "INSUFFICIENT_HISTORY")
    return {"status": status, "ready": ready, "gates": gates, "history": h}


def register_candidate(candidate_type:str,config:Mapping[str,Any],*,dataset_hash:Optional[str]=None,baseline_version:Optional[str]=None,metrics:Optional[Mapping[str,Any]]=None,limitations:Optional[Sequence[str]]=None,actor:str="SYSTEM") -> Dict[str,Any]:
    init_db(); cid=str(uuid.uuid4()); version=_candidate_version(candidate_type,dataset_hash); status="DRAFT" if history_report(MIN_GRADED)["eligible"] else "DISABLED"
    manifest={"candidate_type":candidate_type,"config":dict(config),"dataset_hash":dataset_hash,"baseline_version":baseline_version}
    with _conn() as c:
        c.execute("INSERT INTO model_registry(candidate_id,candidate_type,version,status,created_at,created_by,baseline_version,dataset_hash,config_json,metrics_json,limitations_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(cid,candidate_type,version,status,_now(),actor,baseline_version,dataset_hash,_json(config),_json(metrics or {}),_json(list(limitations or []))))
    audit("CREATE_CANDIDATE","model_candidate",cid,new={"type":candidate_type,"status":status,"manifest_hash":hashlib.sha256(_json(manifest).encode()).hexdigest()},actor=actor)
    return {"candidate_id":cid,"version":version,"status":status,"automatic_promotion":False,"production_effect":"NONE"}


def candidates(candidate_id:Optional[str]=None) -> Any:
    init_db()
    with _conn() as c:
        rows=c.execute("SELECT * FROM model_registry WHERE candidate_id=?",(candidate_id,)).fetchall() if candidate_id else c.execute("SELECT * FROM model_registry ORDER BY created_at DESC").fetchall()
    out=[]
    for r in rows:
        d=dict(r); d["config"]=_load(d.pop("config_json")); d["metrics"]=_load(d.pop("metrics_json")); d["limitations"]=_load(d.pop("limitations_json"),[]); d["production_effect"]="NONE"; d["automatic_promotion"]=False; out.append(d)
    return (out[0] if candidate_id and out else None) if candidate_id else out


def submit_candidate(candidate_id:str,*,actor:str,note:str="") -> Dict[str,Any]:
    init_db(); cur=candidates(candidate_id)
    if not cur: return {"ok":False,"status":"UNAVAILABLE","error":"candidate not found"}
    if cur["status"] not in ("DRAFT","REJECTED"): return {"ok":False,"status":"APPROVAL_REQUIRED","error":"candidate cannot be submitted from current state"}
    with _conn() as c: c.execute("UPDATE model_registry SET status='READY_FOR_REVIEW' WHERE candidate_id=?",(candidate_id,))
    audit("SUBMIT_FOR_REVIEW","model_candidate",candidate_id,previous=cur,new={"status":"READY_FOR_REVIEW"},explanation=note,actor=actor)
    return {"ok":True,"status":"APPROVAL_REQUIRED","candidate_id":candidate_id,"candidate_status":"READY_FOR_REVIEW"}


def record_offline_evaluation(candidate_id:str, manifest:Mapping[str,Any], *, actor:str="SYSTEM") -> Dict[str,Any]:
    init_db(); cur=candidates(candidate_id)
    if not cur: return {"ok":False,"status":"UNAVAILABLE","error":"candidate not found"}
    dataset_hash=str(manifest.get("dataset_hash") or cur.get("dataset_hash") or "").strip(); methodology=dict(manifest.get("methodology") or {}); splits=dict(manifest.get("splits") or {})
    if not dataset_hash or not all(k in splits for k in ("train","validation","test")):
        return {"ok":False,"status":"UNAVAILABLE","error":"dataset_hash and train/validation/test split manifest are required"}
    if methodology.get("look_ahead_guard") is not True or methodology.get("walk_forward") is not True:
        return {"ok":False,"status":"DISABLED","error":"look-ahead guard and walk-forward validation are mandatory"}
    baseline=dict(manifest.get("baseline_metrics") or {}); candidate=dict(manifest.get("candidate_metrics") or {}); comparison=dict(manifest.get("comparison") or {}); limitations=list(manifest.get("limitations") or [])
    body={"candidate_id":candidate_id,"dataset_hash":dataset_hash,"methodology":methodology,"splits":splits,"baseline":baseline,"candidate":candidate,"comparison":comparison,"limitations":limitations}
    integrity=hashlib.sha256(_json(body).encode()).hexdigest(); eid=str(uuid.uuid4()); status="READY_FOR_REVIEW" if history_report(MIN_GRADED)["eligible"] else "INSUFFICIENT_HISTORY"
    with _conn() as c:
        c.execute("INSERT INTO offline_evaluations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(eid,candidate_id,_now(),dataset_hash,_json(methodology),_json(splits),_json(baseline),_json(candidate),_json(comparison),_json(limitations),status,integrity))
        c.execute("UPDATE model_registry SET metrics_json=?, dataset_hash=? WHERE candidate_id=?",(_json({"evaluation_id":eid,"comparison":comparison}),dataset_hash,candidate_id))
    audit("OFFLINE_EVALUATION","model_candidate",candidate_id,new={"evaluation_id":eid,"status":status,"integrity_hash":integrity},actor=actor)
    return {"ok":True,"status":status,"evaluation_id":eid,"integrity_hash":integrity,"production_effect":"NONE"}


def evaluations(candidate_id:Optional[str]=None,limit:int=100) -> List[Dict[str,Any]]:
    init_db()
    with _conn() as c:
        rows=c.execute("SELECT * FROM offline_evaluations WHERE candidate_id=? ORDER BY created_at DESC LIMIT ?",(candidate_id,max(1,min(limit,500)))).fetchall() if candidate_id else c.execute("SELECT * FROM offline_evaluations ORDER BY created_at DESC LIMIT ?",(max(1,min(limit,500)),)).fetchall()
    out=[]
    for r in rows:
        d=dict(r)
        for src,dst,default in (("methodology_json","methodology",{}),("split_manifest_json","splits",{}),("baseline_metrics_json","baseline_metrics",{}),("candidate_metrics_json","candidate_metrics",{}),("comparison_json","comparison",{}),("limitations_json","limitations",[])):
            d[dst]=_load(d.pop(src),default)
        out.append(d)
    return out


def _approval(candidate_id:str,decision:str,actor:str,note:str,new_status:str,evidence:Optional[Mapping[str,Any]]=None) -> str:
    cur=candidates(candidate_id); aid=str(uuid.uuid4())
    with _conn() as c:
        c.execute("INSERT INTO candidate_approvals VALUES(?,?,?,?,?,?,?,?,?)",(aid,candidate_id,decision,actor,_now(),note,cur["status"],new_status,_json(evidence or {})))
        c.execute("UPDATE model_registry SET status=?, approved_at=?, approved_by=? WHERE candidate_id=?",(new_status,_now(),actor,candidate_id))
    audit(decision,"model_candidate",candidate_id,previous=cur,new={"status":new_status},explanation=note,actor=actor)
    return aid


def approve_candidate(candidate_id:str,*,actor:str,note:str="") -> Dict[str,Any]:
    init_db(); cur=candidates(candidate_id)
    if not cur: return {"ok":False,"status":"UNAVAILABLE","error":"candidate not found"}
    ready=readiness_gates()
    if not ready["ready"]: return {"ok":False,"status":"DISABLED","error":"insufficient validated history","readiness":ready}
    if cur["status"] != "READY_FOR_REVIEW": return {"ok":False,"status":"APPROVAL_REQUIRED","error":"candidate must be READY_FOR_REVIEW"}
    ev=evaluations(candidate_id,1)
    if not ev: return {"ok":False,"status":"APPROVAL_REQUIRED","error":"offline evaluation required"}
    aid=_approval(candidate_id,"APPROVE_FOR_SHADOW",actor,note,"SHADOW_ONLY",{"evaluation_id":ev[0]["evaluation_id"]})
    return {"ok":True,"status":"SHADOW_ONLY","candidate_id":candidate_id,"approval_id":aid,"production_effect":"NONE"}


def reject_candidate(candidate_id:str,*,actor:str,note:str="") -> Dict[str,Any]:
    init_db(); cur=candidates(candidate_id)
    if not cur: return {"ok":False,"status":"UNAVAILABLE","error":"candidate not found"}
    aid=_approval(candidate_id,"REJECT",actor,note,"REJECTED")
    return {"ok":True,"status":"DISABLED","candidate_id":candidate_id,"approval_id":aid}


def record_shadow_result(candidate_id:str,production:Mapping[str,Any],candidate:Mapping[str,Any],comparison:Mapping[str,Any],*,data_quality:str="UNKNOWN",observed_at:Optional[str]=None,actor:str="SYSTEM") -> Dict[str,Any]:
    init_db(); cur=candidates(candidate_id)
    if not cur: return {"ok":False,"status":"UNAVAILABLE","error":"candidate not found"}
    if cur["status"] != "SHADOW_ONLY": return {"ok":False,"status":"DISABLED","error":"candidate is not approved for shadow mode"}
    sid=str(uuid.uuid4()); at=observed_at or _now()
    with _conn() as c: c.execute("INSERT INTO shadow_results VALUES(?,?,?,?,?,?,?)",(sid,candidate_id,at,_json(production),_json(candidate),_json(comparison),str(data_quality).upper()))
    audit("SHADOW_OBSERVATION","model_candidate",candidate_id,new={"shadow_id":sid,"data_quality":str(data_quality).upper()},actor=actor)
    return {"ok":True,"status":"SHADOW_ONLY","shadow_id":sid,"candidate_id":candidate_id,"production_changed":False}


def shadows(candidate_id:Optional[str]=None,limit:int=100) -> List[Dict[str,Any]]:
    init_db()
    with _conn() as c:
        rows=c.execute("SELECT * FROM shadow_results WHERE candidate_id=? ORDER BY observed_at DESC LIMIT ?",(candidate_id,max(1,min(limit,500)))).fetchall() if candidate_id else c.execute("SELECT * FROM shadow_results ORDER BY observed_at DESC LIMIT ?",(max(1,min(limit,500)),)).fetchall()
    out=[]
    for r in rows:
        d=dict(r); d["production"]=_load(d.pop("production_json")); d["candidate"]=_load(d.pop("candidate_json")); d["comparison"]=_load(d.pop("comparison_json")); out.append(d)
    return out


def record_drift(metric:str,severity:str,evidence:Mapping[str,Any],*,production_version:Optional[str]=None,candidate_id:Optional[str]=None,status:str="OPEN",actor:str="SYSTEM") -> Dict[str,Any]:
    init_db(); did=str(uuid.uuid4()); sev=str(severity).upper()
    if sev not in ("LOW","MODERATE","HIGH","CRITICAL"): return {"ok":False,"status":"UNAVAILABLE","error":"invalid severity"}
    with _conn() as c: c.execute("INSERT INTO drift_events VALUES(?,?,?,?,?,?,?,?)",(did,_now(),metric,sev,production_version,candidate_id,_json(evidence),status))
    audit("DRIFT_DETECTED","drift_event",did,new={"metric":metric,"severity":sev,"candidate_id":candidate_id},actor=actor)
    return {"ok":True,"status":"DEGRADED" if sev in ("HIGH","CRITICAL") else "READY","drift_id":did}


def rollback(candidate_id:str,*,actor:str,note:str="",restored_version:Optional[str]=None) -> Dict[str,Any]:
    init_db(); cur=candidates(candidate_id)
    if not cur: return {"ok":False,"status":"UNAVAILABLE","error":"candidate not found"}
    rid=str(uuid.uuid4())
    with _conn() as c:
        c.execute("UPDATE model_registry SET status='ROLLED_BACK' WHERE candidate_id=?",(candidate_id,))
        c.execute("INSERT INTO rollback_history VALUES(?,?,?,?,?,?,?,?)",(rid,candidate_id,actor,_now(),cur["status"],restored_version,note,_json({"production_effect":"NONE"})))
    audit("ROLLBACK","model_candidate",candidate_id,previous=cur,new={"status":"ROLLED_BACK","restored_version":restored_version},explanation=note,actor=actor)
    return {"ok":True,"status":"DISABLED","candidate_id":candidate_id,"rollback_id":rid,"rollback_complete":True,"production_changed":False}


def approvals(candidate_id:Optional[str]=None,limit:int=100) -> List[Dict[str,Any]]:
    init_db()
    with _conn() as c:
        rows=c.execute("SELECT * FROM candidate_approvals WHERE candidate_id=? ORDER BY decided_at DESC LIMIT ?",(candidate_id,max(1,min(limit,500)))).fetchall() if candidate_id else c.execute("SELECT * FROM candidate_approvals ORDER BY decided_at DESC LIMIT ?",(max(1,min(limit,500)),)).fetchall()
    out=[]
    for r in rows:
        d=dict(r); d["evidence"]=_load(d.pop("evidence_json")); out.append(d)
    return out


def rollbacks(limit:int=100) -> List[Dict[str,Any]]:
    init_db()
    with _conn() as c: rows=c.execute("SELECT * FROM rollback_history ORDER BY rolled_back_at DESC LIMIT ?",(max(1,min(limit,500)),)).fetchall()
    out=[]
    for r in rows:
        d=dict(r); d["metadata"]=_load(d.pop("metadata_json")); out.append(d)
    return out


def learning_status() -> Dict[str,Any]:
    ready=readiness_gates(); rows=candidates(); shadow=[r for r in rows if r["status"]=="SHADOW_ONLY"]; review=[r for r in rows if r["status"]=="READY_FOR_REVIEW"]
    if shadow: status="SHADOW_ONLY"
    elif review: status="APPROVAL_REQUIRED"
    elif ready["ready"]: status="READY_FOR_OFFLINE_RESEARCH"
    elif ready["history"]["sample_size"]: status="INSUFFICIENT_HISTORY"
    else: status="DISABLED"
    return {"schema_version":"apex.learning.status.v2","status":status,"adaptive_learning_enabled":False,"autonomous_weighting":False,"automatic_promotion":False,"production_policy_mutation":False,"readiness":ready,"candidate_count":len(rows),"shadow_candidate_count":len(shadow),"approval_queue_count":len(review),"evaluation_count":len(evaluations()),"shadow_observation_count":len(shadows()),"promotion_gate":{"human_approval_required":True,"walk_forward_required":True,"train_validation_test_separation_required":True,"look_ahead_guard_required":True,"rollback_required":True,"automatic_production_promotion":False},"disabled_reason":None if ready["ready"] else "Insufficient real graded history or quality coverage","build_version":VERSION}


def audits(limit:int=100) -> List[Dict[str,Any]]:
    init_db()
    with _conn() as c: rows=c.execute("SELECT * FROM governance_audit ORDER BY occurred_at DESC LIMIT ?",(max(1,min(limit,500)),)).fetchall()
    out=[]
    for r in rows:
        d=dict(r); d["previous"]=_load(d.pop("previous_json")); d["new"]=_load(d.pop("new_json")); out.append(d)
    return out


def drift(limit:int=100) -> List[Dict[str,Any]]:
    init_db()
    with _conn() as c: rows=c.execute("SELECT * FROM drift_events ORDER BY detected_at DESC LIMIT ?",(max(1,min(limit,500)),)).fetchall()
    out=[]
    for r in rows:
        d=dict(r); d["evidence"]=_load(d.pop("evidence_json")); out.append(d)
    return out
