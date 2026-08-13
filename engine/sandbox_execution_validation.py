"""APEX 16.9.1 — End-to-End E*TRADE Sandbox Execution Validation.

Deterministic certification harness for the complete confirmation-gated execution
lifecycle. It never enables live trading and never stores credentials. Broker calls
are injected adapters, allowing repeatable sandbox certification and failure drills.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, sqlite3, uuid
from typing import Any, Callable
from . import institutional_governance as gov

VERSION='16.9.1'; SCHEMA_VERSION='apex.sandbox_execution_validation.v1'
REQUIRED_CHECKS=(
 'OAUTH_CONFIGURED','ACCOUNT_RESOLVED','BROKER_SYNC_HEALTHY','TRADEABILITY_PASS',
 'RISK_GATE_PASS','OPTION_SYMBOL_VALID','PREVIEW_ACCEPTED','CONFIRMATION_BOUND',
 'SUBMISSION_ACCEPTED','DUPLICATE_PREVENTED','ORDER_TRACKED','FILL_RECONCILED',
 'POSITION_SYNCED','MANAGEMENT_HANDOFF','KILL_SWITCH_VERIFIED')
CERT_STATES=('NOT_RUN','RUNNING','PASSED','FAILED','PARTIAL','BLOCKED')

def _now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def _json(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def _hash(v): return hashlib.sha256(_json(v).encode()).hexdigest()
def _conn():
 c=sqlite3.connect(gov.DB_PATH); c.row_factory=sqlite3.Row; return c

def init_db():
 gov.init_db()
 with _conn() as c:
  c.executescript('''
  CREATE TABLE IF NOT EXISTS sandbox_validation_runs(
   run_id TEXT PRIMARY KEY,account_id TEXT NOT NULL,started_at TEXT NOT NULL,
   completed_at TEXT,state TEXT NOT NULL,score REAL NOT NULL,request_json TEXT NOT NULL,
   result_json TEXT NOT NULL,schema_version TEXT NOT NULL,engine_version TEXT NOT NULL,
   integrity_hash TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS sandbox_validation_events(
   event_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,sequence_no INTEGER NOT NULL,
   observed_at TEXT NOT NULL,check_name TEXT NOT NULL,status TEXT NOT NULL,
   detail_json TEXT NOT NULL,integrity_hash TEXT NOT NULL,
   UNIQUE(run_id,sequence_no));
  ''')
 return {'ok':True,'schema_version':SCHEMA_VERSION,'build_version':VERSION}

def _check(name:str, passed:bool, detail:Any=None, blocking:bool=False)->dict[str,Any]:
 return {'check':name,'status':'PASS' if passed else ('BLOCKED' if blocking else 'FAIL'),
         'passed':bool(passed),'blocking':bool(blocking and not passed),'detail':detail or {}}

def _bool_path(payload:dict,*paths,default=False):
 for path in paths:
  cur=payload
  ok=True
  for part in path.split('.'):
   if isinstance(cur,dict) and part in cur: cur=cur[part]
   else: ok=False; break
  if ok:return bool(cur)
 return default

def validate_osi_key(osi_key:str)->bool:
 s=str(osi_key or '').strip().upper()
 # Flexible guard: SPX/SPXW root + YYMMDD + C/P + 8-digit strike encoding.
 if len(s)<15:return False
 tail=s[-15:]
 return tail[:6].isdigit() and tail[6] in ('C','P') and tail[7:].isdigit() and s[:-15].isalnum()

def evaluate(payload:dict|None=None)->dict[str,Any]:
 p=payload or {}; cfg=p.get('configuration') if isinstance(p.get('configuration'),dict) else {}
 gates=p.get('gates') if isinstance(p.get('gates'),dict) else {}
 preview=p.get('preview') if isinstance(p.get('preview'),dict) else {}
 confirmation=p.get('confirmation') if isinstance(p.get('confirmation'),dict) else {}
 submission=p.get('submission') if isinstance(p.get('submission'),dict) else {}
 tracking=p.get('tracking') if isinstance(p.get('tracking'),dict) else {}
 reconciliation=p.get('reconciliation') if isinstance(p.get('reconciliation'),dict) else {}
 drills=p.get('failure_drills') if isinstance(p.get('failure_drills'),dict) else {}
 checks=[]
 checks.append(_check('OAUTH_CONFIGURED',_bool_path(cfg,'oauth_configured','credentials_present'),{'mode':cfg.get('mode','SANDBOX')},True))
 checks.append(_check('ACCOUNT_RESOLVED',bool(cfg.get('account_id_key') or cfg.get('account_resolved')),{'account_id':cfg.get('account_id')},True))
 checks.append(_check('BROKER_SYNC_HEALTHY',str(gates.get('broker_sync_state','')).upper() in ('SYNCED','PARTIAL'),{'state':gates.get('broker_sync_state')},True))
 checks.append(_check('TRADEABILITY_PASS',str(gates.get('tradeability','')).upper() in ('TRADEABLE','TRADEABLE_WITH_CAUTION'),{'state':gates.get('tradeability')},True))
 checks.append(_check('RISK_GATE_PASS',bool(gates.get('risk_passed')),{'risk_state':gates.get('risk_state')},True))
 checks.append(_check('OPTION_SYMBOL_VALID',validate_osi_key(str(p.get('osi_key') or '')),{'osi_key':p.get('osi_key')},True))
 checks.append(_check('PREVIEW_ACCEPTED',bool(preview.get('ok') and (preview.get('preview_id') or preview.get('broker_preview_id'))),preview,True))
 bound=bool(confirmation.get('acknowledgement') and confirmation.get('confirmed_by') and confirmation.get('intent_id') and confirmation.get('preview_record_id'))
 checks.append(_check('CONFIRMATION_BOUND',bound,{'confirmed_by':confirmation.get('confirmed_by')},True))
 checks.append(_check('SUBMISSION_ACCEPTED',bool(submission.get('ok') and (submission.get('order_id') or submission.get('broker_order_id'))),submission,True))
 checks.append(_check('DUPLICATE_PREVENTED',bool(drills.get('duplicate_submission_prevented')),{},True))
 checks.append(_check('ORDER_TRACKED',str(tracking.get('order_status','')).upper() in ('OPEN','PARTIAL','FILLED','EXECUTED'),tracking))
 checks.append(_check('FILL_RECONCILED',bool(reconciliation.get('fill_reconciled')),reconciliation))
 checks.append(_check('POSITION_SYNCED',bool(reconciliation.get('position_synced')),reconciliation))
 checks.append(_check('MANAGEMENT_HANDOFF',bool(reconciliation.get('management_handoff')),reconciliation))
 checks.append(_check('KILL_SWITCH_VERIFIED',bool(drills.get('kill_switch_verified')),{},True))
 passed=sum(1 for x in checks if x['passed']); score=round(100*passed/len(REQUIRED_CHECKS),2)
 blocking=[x['check'] for x in checks if x['blocking']]
 state='PASSED' if passed==len(REQUIRED_CHECKS) else ('BLOCKED' if blocking else ('PARTIAL' if passed else 'FAILED'))
 return {'status':state,'certification_score':score,'checks_passed':passed,'checks_total':len(REQUIRED_CHECKS),
         'blocking_checks':blocking,'checks':checks,'sandbox_only':True,'production_execution_certified':False,
         'human_confirmation_required':True,'automatic_execution_enabled':False,'production_effect':'NONE'}

def record(payload:dict,actor='API')->dict[str,Any]:
 init_db(); result=evaluate(payload); rid=str(payload.get('run_id') or uuid.uuid4()); started=str(payload.get('started_at') or _now()); completed=_now()
 with _conn() as c:r=c.execute('SELECT * FROM sandbox_validation_runs WHERE run_id=?',(rid,)).fetchone()
 if r:return {'ok':True,'status':'IMMUTABLE_EXISTS','created':False,'run_id':rid,'result':json.loads(r['result_json']),'integrity_hash':r['integrity_hash']}
 body={'run_id':rid,'actor':actor,'account_id':str(payload.get('account_id') or 'PRIMARY'),'started_at':started,'completed_at':completed,**result}; ih=_hash(body)
 with _conn() as c:
  c.execute('INSERT INTO sandbox_validation_runs VALUES(?,?,?,?,?,?,?,?,?,?,?)',(rid,body['account_id'],started,completed,result['status'],result['certification_score'],_json(payload),_json(body),SCHEMA_VERSION,VERSION,ih))
  for seq,chk in enumerate(result['checks'],1):
   eid=str(uuid.uuid4()); detail={'run_id':rid,'sequence_no':seq,**chk}; c.execute('INSERT INTO sandbox_validation_events VALUES(?,?,?,?,?,?,?,?)',(eid,rid,seq,completed,chk['check'],chk['status'],_json(detail),_hash(detail)))
 return {'ok':True,'status':result['status'],'created':True,'run_id':rid,'result':body,'integrity_hash':ih,'production_effect':'NONE'}

def history(limit=50):
 init_db()
 with _conn() as c: rows=c.execute('SELECT * FROM sandbox_validation_runs ORDER BY started_at DESC LIMIT ?',(max(1,min(int(limit),500)),)).fetchall()
 return [{**dict(r),'request':json.loads(r['request_json']),'result':json.loads(r['result_json'])} for r in rows]

def latest(account_id='PRIMARY'):
 init_db()
 with _conn() as c:r=c.execute('SELECT * FROM sandbox_validation_runs WHERE account_id=? ORDER BY started_at DESC LIMIT 1',(account_id,)).fetchone()
 if not r:return {'ok':True,'status':'NOT_RUN','account_id':account_id,'sandbox_only':True,'production_effect':'NONE'}
 return {'ok':True,**json.loads(r['result_json']),'integrity_hash':r['integrity_hash']}

def status():
 init_db()
 with _conn() as c:n=c.execute('SELECT COUNT(*) n FROM sandbox_validation_runs').fetchone()['n']
 return {'status':'READY','engine':'SANDBOX_EXECUTION_VALIDATION','build_version':VERSION,'schema_version':SCHEMA_VERSION,
         'validation_run_count':n,'required_checks':list(REQUIRED_CHECKS),'sandbox_only':True,
         'automatic_execution_enabled':False,'live_trading_enabled':False,'human_confirmation_required':True,'production_effect':'NONE'}

def dashboard(account_id='PRIMARY',limit=10):
 return {'ok':True,'status':'READY','safety':status(),'latest_certification':latest(account_id),'recent_runs':history(limit)}
