"""APEX 18.1.7 — Confirmation-Gated Premium Execution Orchestrator.

Creates immutable order intents and previews from a risk-approved premium
portfolio. Submission remains disabled unless an executor is supplied, the
runtime switch is enabled, and a fresh one-time human confirmation is provided.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, os, sqlite3, uuid
from typing import Any, Callable, Dict, Optional

VERSION="18.1.7_CONFIRMATION_GATED_EXECUTION_ORCHESTRATOR"

def _json(v): return json.dumps(v,sort_keys=True,separators=(",",":"),default=str)
def _hash(v): return hashlib.sha256(_json(v).encode()).hexdigest()
def _now(): return dt.datetime.now(dt.timezone.utc)

class PremiumExecutionOrchestrator:
    def __init__(self,db_path:Optional[str]=None,executor:Optional[Callable[[Dict[str,Any]],Dict[str,Any]]]=None):
        self.db_path=db_path or os.getenv("DB_PATH","apex_tracking.db"); self.executor=executor; self._init()
    def _connect(self):
        c=sqlite3.connect(self.db_path); c.row_factory=sqlite3.Row; return c
    def _init(self):
        with self._connect() as c:c.executescript("""
        CREATE TABLE IF NOT EXISTS premium_execution_intents(
          intent_id TEXT PRIMARY KEY,idempotency_key TEXT UNIQUE NOT NULL,created_at TEXT NOT NULL,ticker TEXT NOT NULL,
          state TEXT NOT NULL,intent_json TEXT NOT NULL,preview_json TEXT,preview_expires_at TEXT,
          confirmation_json TEXT,confirmation_expires_at TEXT,submission_json TEXT,updated_at TEXT NOT NULL);
        """)
    def create_intent(self,ticker:str,portfolio:Dict[str,Any],risk:Dict[str,Any],execution_reality:Dict[str,Any],idempotency_key:Optional[str]=None):
        selected=portfolio.get("selected_positions") or []
        blockers=[]
        if not risk.get("approved"): blockers.append("Portfolio Risk Governor approval is required.")
        if execution_reality.get("state")!="EXECUTABLE": blockers.append("Execution Reality approval is required.")
        if not selected: blockers.append("No selected premium positions are available.")
        if blockers:return {"ok":False,"status":"BLOCKED","blockers":blockers,"production_effect":"NONE"}
        body={"ticker":ticker.upper(),"positions":[{"strategy":p.get("strategy"),"contracts":p.get("contracts"),"candidate":p.get("candidate"),"allocated_risk":p.get("allocated_risk")} for p in selected],
              "portfolio_summary":portfolio.get("portfolio_summary"),"risk_governor":risk,"execution_reality":execution_reality,
              "created_at":_now().isoformat(),"execution_authority":False}
        key=idempotency_key or _hash({"ticker":ticker.upper(),"positions":body["positions"],"minute":body["created_at"][:16]})
        with self._connect() as c:r=c.execute("SELECT * FROM premium_execution_intents WHERE idempotency_key=?",(key,)).fetchone()
        if r:return {"ok":True,"status":"IMMUTABLE_EXISTS","intent":self._row(r),"production_effect":"NONE"}
        iid=str(uuid.uuid4()); now=_now().isoformat()
        with self._connect() as c:c.execute("INSERT INTO premium_execution_intents(intent_id,idempotency_key,created_at,ticker,state,intent_json,updated_at) VALUES(?,?,?,?,?,?,?)",(iid,key,now,ticker.upper(),"DRAFT",_json(body),now))
        return {"ok":True,"status":"CREATED","intent_id":iid,"state":"DRAFT","intent":body,"production_effect":"NONE"}
    def preview(self,intent_id:str,ttl_seconds:int=120):
        with self._connect() as c:r=c.execute("SELECT * FROM premium_execution_intents WHERE intent_id=?",(intent_id,)).fetchone()
        if not r:return {"ok":False,"status":"NOT_FOUND"}
        intent=json.loads(r["intent_json"]); er=intent.get("execution_reality") or {}; rec=er.get("recommendation") or {}
        now=_now(); exp=now+dt.timedelta(seconds=max(30,min(int(ttl_seconds),600)))
        preview={"intent_id":intent_id,"generated_at":now.isoformat(),"expires_at":exp.isoformat(),"positions":intent.get("positions"),
                 "shadow_fill_credit":rec.get("shadow_fill_credit"),"maximum_acceptable_entry_credit":rec.get("maximum_acceptable_entry_credit"),
                 "execution_adjusted_expected_value":rec.get("execution_adjusted_expected_value"),"confirmation_required":True,"broker_submission":False}
        with self._connect() as c:c.execute("UPDATE premium_execution_intents SET state='PREVIEWED',preview_json=?,preview_expires_at=?,updated_at=? WHERE intent_id=?",(_json(preview),exp.isoformat(),now.isoformat(),intent_id))
        return {"ok":True,"status":"PREVIEWED","preview":preview,"production_effect":"PREVIEW_ONLY"}
    def confirm(self,intent_id:str,confirmed_by:str,acknowledgement:bool,ttl_seconds:int=90):
        if not acknowledgement or not str(confirmed_by).strip():return {"ok":False,"status":"CONFIRMATION_REQUIRED"}
        with self._connect() as c:r=c.execute("SELECT * FROM premium_execution_intents WHERE intent_id=?",(intent_id,)).fetchone()
        if not r:return {"ok":False,"status":"NOT_FOUND"}
        if r["state"]!="PREVIEWED":return {"ok":False,"status":"PREVIEW_REQUIRED"}
        if not r["preview_expires_at"] or dt.datetime.fromisoformat(r["preview_expires_at"])<=_now():return {"ok":False,"status":"PREVIEW_EXPIRED"}
        now=_now(); exp=now+dt.timedelta(seconds=max(30,min(int(ttl_seconds),300))); token=str(uuid.uuid4())
        conf={"confirmation_id":token,"confirmed_by":str(confirmed_by).strip(),"confirmed_at":now.isoformat(),"expires_at":exp.isoformat(),"explicit_acknowledgement":True,"one_time_use":True}
        with self._connect() as c:c.execute("UPDATE premium_execution_intents SET state='CONFIRMED',confirmation_json=?,confirmation_expires_at=?,updated_at=? WHERE intent_id=?",(_json(conf),exp.isoformat(),now.isoformat(),intent_id))
        return {"ok":True,"status":"CONFIRMED","confirmation":conf,"production_effect":"NONE"}
    def submit(self,intent_id:str,confirmation_id:str,revalidation:Dict[str,Any]):
        with self._connect() as c:r=c.execute("SELECT * FROM premium_execution_intents WHERE intent_id=?",(intent_id,)).fetchone()
        if not r:return {"ok":False,"status":"NOT_FOUND"}
        if r["submission_json"]:return {"ok":True,"status":"IDEMPOTENT_REPLAY","submission":json.loads(r["submission_json"])}
        conf=json.loads(r["confirmation_json"] or "{}")
        if conf.get("confirmation_id")!=confirmation_id:return {"ok":False,"status":"INVALID_CONFIRMATION"}
        if not r["confirmation_expires_at"] or dt.datetime.fromisoformat(r["confirmation_expires_at"])<=_now():return {"ok":False,"status":"CONFIRMATION_EXPIRED"}
        blockers=[]
        if not (revalidation.get("risk_governor") or {}).get("approved"):blockers.append("Risk approval failed revalidation.")
        if (revalidation.get("execution_reality") or {}).get("state")!="EXECUTABLE":blockers.append("Execution Reality failed revalidation.")
        if blockers:return {"ok":False,"status":"BLOCKED","blockers":blockers,"production_effect":"NONE"}
        enabled=os.getenv("APEX_PREMIUM_EXECUTION_ENABLED","false").lower()=="true"
        if not enabled or self.executor is None:return {"ok":False,"status":"EXECUTION_DISABLED","confirmation_valid":True,"required_env":"APEX_PREMIUM_EXECUTION_ENABLED=true","production_effect":"NONE"}
        result=self.executor(json.loads(r["intent_json"])) or {}; now=_now().isoformat(); status="SUBMITTED" if result.get("ok") else "REJECTED"
        submission={"submission_id":str(uuid.uuid4()),"intent_id":intent_id,"submitted_at":now,"status":status,"broker_result":result,"human_confirmed":True,"automatic_execution":False}
        with self._connect() as c:c.execute("UPDATE premium_execution_intents SET state=?,submission_json=?,updated_at=? WHERE intent_id=?",(status,_json(submission),now,intent_id))
        return {"ok":bool(result.get("ok")),"status":status,"submission":submission,"production_effect":"BROKER_SUBMISSION" if result.get("ok") else "NONE"}
    def recent(self,limit=100):
        with self._connect() as c:rows=c.execute("SELECT * FROM premium_execution_intents ORDER BY created_at DESC LIMIT ?",(max(1,min(int(limit),500)),)).fetchall()
        return [self._row(r) for r in rows]
    @staticmethod
    def _row(r):
        d=dict(r)
        for k in ("intent_json","preview_json","confirmation_json","submission_json"):
            if d.get(k): d[k[:-5] if k.endswith("_json") else k]=json.loads(d[k])
        return d
