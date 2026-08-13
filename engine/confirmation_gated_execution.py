"""APEX 16.9 — Confirmation-Gated Execution.

Governed order-intent, preview, explicit-confirmation and execution audit layer.
No automatic execution. Broker submission requires a valid preview, a one-time human
confirmation, passing risk/tradeability/broker-sync gates, and an explicitly enabled
runtime adapter. All records are immutable and idempotent.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, os, sqlite3, uuid
from typing import Any, Callable
from . import institutional_governance as gov

VERSION='16.9.16.9'; SCHEMA_VERSION='apex.confirmation_execution.v1'
INTENT_STATES=('DRAFT','PREVIEWED','CONFIRMED','SUBMITTED','FILLED','REJECTED','EXPIRED','CANCELED','BLOCKED')
ALLOWED_ACTIONS=('BUY_OPEN','SELL_CLOSE','SELL_OPEN','BUY_CLOSE')
ALLOWED_ORDER_TYPES=('LIMIT','MARKET','STOP','STOP_LIMIT')

def _now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def _json(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def _hash(v): return hashlib.sha256(_json(v).encode()).hexdigest()
def _conn():
 c=sqlite3.connect(gov.DB_PATH); c.row_factory=sqlite3.Row; return c

def init_db():
 gov.init_db()
 with _conn() as c:
  c.executescript('''
  CREATE TABLE IF NOT EXISTS execution_intents(
   intent_id TEXT PRIMARY KEY,idempotency_key TEXT NOT NULL UNIQUE,account_id TEXT NOT NULL,
   symbol TEXT NOT NULL,created_at TEXT NOT NULL,state TEXT NOT NULL,intent_json TEXT NOT NULL,
   schema_version TEXT NOT NULL,engine_version TEXT NOT NULL,integrity_hash TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS execution_previews(
   preview_record_id TEXT PRIMARY KEY,intent_id TEXT NOT NULL,broker_preview_id TEXT,
   observed_at TEXT NOT NULL,expires_at TEXT NOT NULL,preview_json TEXT NOT NULL,
   schema_version TEXT NOT NULL,engine_version TEXT NOT NULL,integrity_hash TEXT NOT NULL,
   UNIQUE(intent_id,observed_at));
  CREATE TABLE IF NOT EXISTS execution_confirmations(
   confirmation_id TEXT PRIMARY KEY,intent_id TEXT NOT NULL,preview_record_id TEXT NOT NULL,
   confirmed_by TEXT NOT NULL,confirmed_at TEXT NOT NULL,expires_at TEXT NOT NULL,
   confirmation_json TEXT NOT NULL,schema_version TEXT NOT NULL,engine_version TEXT NOT NULL,
   integrity_hash TEXT NOT NULL,UNIQUE(intent_id,preview_record_id));
  CREATE TABLE IF NOT EXISTS execution_submissions(
   submission_id TEXT PRIMARY KEY,intent_id TEXT NOT NULL,confirmation_id TEXT NOT NULL UNIQUE,
   submitted_at TEXT NOT NULL,status TEXT NOT NULL,broker_order_id TEXT,submission_json TEXT NOT NULL,
   schema_version TEXT NOT NULL,engine_version TEXT NOT NULL,integrity_hash TEXT NOT NULL);
  ''')
 return {'ok':True,'schema_version':SCHEMA_VERSION,'build_version':VERSION}

def _num(v,d=0.0):
 try:return float(v)
 except Exception:return d

def normalize_intent(payload:dict|None=None)->dict[str,Any]:
 p=payload or {}; qty=max(0,int(_num(p.get('quantity'),0)))
 action=str(p.get('action') or '').upper(); typ=str(p.get('order_type') or 'LIMIT').upper()
 return {'account_id':str(p.get('account_id') or 'PRIMARY'),'symbol':str(p.get('symbol') or '').upper().replace(' ',''),
  'osi_key':str(p.get('osi_key') or p.get('option_symbol') or ''),'action':action,'quantity':qty,
  'order_type':typ,'limit_price':_num(p.get('limit_price')) or None,'stop_price':_num(p.get('stop_price')) or None,
  'time_in_force':str(p.get('time_in_force') or 'DAY').upper(),'strategy':str(p.get('strategy') or ''),
  'max_risk':_num(p.get('max_risk')),'expected_debit_credit':_num(p.get('expected_debit_credit')),
  'created_by':str(p.get('created_by') or p.get('actor') or 'API'),'metadata':p.get('metadata') if isinstance(p.get('metadata'),dict) else {}}

def validate_intent(intent:dict)->list[str]:
 e=[]
 if not intent['symbol']: e.append('SYMBOL_REQUIRED')
 if not intent['osi_key']: e.append('OSI_KEY_REQUIRED')
 if intent['action'] not in ALLOWED_ACTIONS:e.append('INVALID_ACTION')
 if intent['order_type'] not in ALLOWED_ORDER_TYPES:e.append('INVALID_ORDER_TYPE')
 if intent['quantity']<1:e.append('QUANTITY_REQUIRED')
 if intent['order_type'] in ('LIMIT','STOP_LIMIT') and not intent['limit_price']:e.append('LIMIT_PRICE_REQUIRED')
 if intent['order_type'] in ('STOP','STOP_LIMIT') and not intent['stop_price']:e.append('STOP_PRICE_REQUIRED')
 return e

def gates(payload:dict|None=None)->dict[str,Any]:
 p=payload or {}; tradeability=str(p.get('tradeability') or p.get('live_operations',{}).get('tradeability') or 'NOT_TRADEABLE').upper()
 risk=p.get('portfolio_risk') if isinstance(p.get('portfolio_risk'),dict) else {}
 broker=p.get('broker_sync') if isinstance(p.get('broker_sync'),dict) else {}
 blocks=[]
 if tradeability not in ('TRADEABLE','TRADEABLE_WITH_CAUTION'):blocks.append('TRADEABILITY_BLOCK')
 if risk and not bool((risk.get('permissions') or {}).get('new_entries_allowed',risk.get('new_entries_allowed',False))):blocks.append('RISK_PERMISSION_BLOCK')
 if str(risk.get('risk_state') or '').upper() in ('BREACH','LOCKED_OUT'):blocks.append('RISK_STATE_BLOCK')
 if broker and str(broker.get('sync_state') or '').upper() not in ('SYNCED','PARTIAL'):blocks.append('BROKER_SYNC_BLOCK')
 if broker and int(broker.get('blocking_discrepancy_count') or 0)>0:blocks.append('BROKER_DISCREPANCY_BLOCK')
 return {'passed':not blocks,'blocking_reasons':blocks,'tradeability':tradeability,
  'risk_state':risk.get('risk_state'),'broker_sync_state':broker.get('sync_state')}

def create_intent(payload:dict, idempotency_key:str|None=None)->dict[str,Any]:
 init_db(); intent=normalize_intent(payload); errors=validate_intent(intent)
 if errors:return {'ok':False,'status':'INVALID_INTENT','errors':errors,'production_effect':'NONE'}
 key=str(idempotency_key or payload.get('idempotency_key') or _hash(intent))
 with _conn() as c:r=c.execute('SELECT * FROM execution_intents WHERE idempotency_key=?',(key,)).fetchone()
 if r:return {'ok':True,'status':'IMMUTABLE_EXISTS','created':False,'intent_id':r['intent_id'],'state':r['state'],'intent':json.loads(r['intent_json']),'integrity_hash':r['integrity_hash']}
 iid=str(uuid.uuid4()); now=_now(); body={**intent,'intent_id':iid,'idempotency_key':key,'state':'DRAFT'}; ih=_hash(body)
 with _conn() as c:c.execute('INSERT INTO execution_intents VALUES(?,?,?,?,?,?,?,?,?,?)',(iid,key,intent['account_id'],intent['symbol'],now,'DRAFT',_json(body),SCHEMA_VERSION,VERSION,ih))
 return {'ok':True,'status':'CREATED','created':True,'intent_id':iid,'state':'DRAFT','intent':body,'integrity_hash':ih,'production_effect':'NONE'}

def preview(intent_id:str, gate_snapshot:dict, broker_preview:dict|None=None, ttl_seconds:int=120)->dict[str,Any]:
 init_db()
 with _conn() as c:r=c.execute('SELECT * FROM execution_intents WHERE intent_id=?',(intent_id,)).fetchone()
 if not r:return {'ok':False,'status':'NOT_FOUND'}
 g=gates(gate_snapshot)
 if not g['passed']:
  with _conn() as c:c.execute('UPDATE execution_intents SET state=? WHERE intent_id=?',('BLOCKED',intent_id))
  return {'ok':False,'status':'BLOCKED','intent_id':intent_id,'gates':g,'production_effect':'NONE'}
 now=dt.datetime.now(dt.timezone.utc); exp=now+dt.timedelta(seconds=max(30,min(int(ttl_seconds),600)))
 bp=broker_preview if isinstance(broker_preview,dict) else {}
 rec={'intent_id':intent_id,'broker_preview_id':str(bp.get('preview_id') or bp.get('broker_preview_id') or ''),
  'estimated_total_cost':_num(bp.get('estimated_total_cost') or bp.get('total_order_value')),
  'estimated_commission':_num(bp.get('estimated_commission') or bp.get('commission')),
  'estimated_fees':_num(bp.get('estimated_fees') or bp.get('fees')),'messages':bp.get('messages') or [],
  'gates':g,'observed_at':now.isoformat(),'expires_at':exp.isoformat(),'broker_mode':str(bp.get('mode') or 'SANDBOX').upper(),
  'preview_only':True}
 pid=str(uuid.uuid4()); ih=_hash(rec)
 with _conn() as c:
  c.execute('INSERT INTO execution_previews VALUES(?,?,?,?,?,?,?,?,?)',(pid,intent_id,rec['broker_preview_id'],rec['observed_at'],rec['expires_at'],_json(rec),SCHEMA_VERSION,VERSION,ih)); c.execute('UPDATE execution_intents SET state=? WHERE intent_id=?',('PREVIEWED',intent_id))
 return {'ok':True,'status':'PREVIEWED','preview_record_id':pid,'preview':rec,'integrity_hash':ih,'production_effect':'PREVIEW_ONLY'}

def confirm(intent_id:str,preview_record_id:str,confirmed_by:str,acknowledgement:bool,ttl_seconds:int=90)->dict[str,Any]:
 init_db()
 if not acknowledgement or not str(confirmed_by).strip():return {'ok':False,'status':'CONFIRMATION_REQUIRED','production_effect':'NONE'}
 with _conn() as c:p=c.execute('SELECT * FROM execution_previews WHERE preview_record_id=? AND intent_id=?',(preview_record_id,intent_id)).fetchone()
 if not p:return {'ok':False,'status':'PREVIEW_NOT_FOUND'}
 if dt.datetime.fromisoformat(p['expires_at'])<=dt.datetime.now(dt.timezone.utc):return {'ok':False,'status':'PREVIEW_EXPIRED'}
 with _conn() as c:r=c.execute('SELECT * FROM execution_confirmations WHERE intent_id=? AND preview_record_id=?',(intent_id,preview_record_id)).fetchone()
 if r:return {'ok':True,'status':'IMMUTABLE_EXISTS','confirmation_id':r['confirmation_id'],'integrity_hash':r['integrity_hash']}
 now=dt.datetime.now(dt.timezone.utc); exp=now+dt.timedelta(seconds=max(30,min(int(ttl_seconds),300))); cid=str(uuid.uuid4())
 body={'confirmation_id':cid,'intent_id':intent_id,'preview_record_id':preview_record_id,'confirmed_by':confirmed_by.strip(),'confirmed_at':now.isoformat(),'expires_at':exp.isoformat(),'explicit_acknowledgement':True,'one_time_use':True}; ih=_hash(body)
 with _conn() as c:
  c.execute('INSERT INTO execution_confirmations VALUES(?,?,?,?,?,?,?,?,?,?)',(cid,intent_id,preview_record_id,confirmed_by.strip(),body['confirmed_at'],body['expires_at'],_json(body),SCHEMA_VERSION,VERSION,ih)); c.execute('UPDATE execution_intents SET state=? WHERE intent_id=?',('CONFIRMED',intent_id))
 return {'ok':True,'status':'CONFIRMED','confirmation_id':cid,'confirmation':body,'integrity_hash':ih,'production_effect':'NONE'}

def execute(intent_id:str,confirmation_id:str,gate_snapshot:dict,executor:Callable[[dict,dict],dict]|None=None)->dict[str,Any]:
 init_db()
 with _conn() as c:
  i=c.execute('SELECT * FROM execution_intents WHERE intent_id=?',(intent_id,)).fetchone(); cf=c.execute('SELECT * FROM execution_confirmations WHERE confirmation_id=? AND intent_id=?',(confirmation_id,intent_id)).fetchone(); used=c.execute('SELECT * FROM execution_submissions WHERE confirmation_id=?',(confirmation_id,)).fetchone()
 if used:return {'ok':True,'status':'IDEMPOTENT_REPLAY','submission_id':used['submission_id'],'submission':json.loads(used['submission_json']),'integrity_hash':used['integrity_hash']}
 if not i or not cf:return {'ok':False,'status':'INVALID_CONFIRMATION','production_effect':'NONE'}
 if dt.datetime.fromisoformat(cf['expires_at'])<=dt.datetime.now(dt.timezone.utc):return {'ok':False,'status':'CONFIRMATION_EXPIRED','production_effect':'NONE'}
 g=gates(gate_snapshot)
 if not g['passed']:return {'ok':False,'status':'BLOCKED','gates':g,'production_effect':'NONE'}
 enabled=os.getenv('APEX_CONFIRMATION_GATED_EXECUTION_ENABLED','false').lower()=='true'
 if executor is None or not enabled:return {'ok':False,'status':'EXECUTION_DISABLED','gates':g,'confirmation_valid':True,'required_env':'APEX_CONFIRMATION_GATED_EXECUTION_ENABLED=true','production_effect':'NONE'}
 intent=json.loads(i['intent_json']); result=executor(intent,json.loads(cf['confirmation_json'])) or {}; ok=bool(result.get('ok')); state='SUBMITTED' if ok else 'REJECTED'; sid=str(uuid.uuid4()); now=_now()
 body={'submission_id':sid,'intent_id':intent_id,'confirmation_id':confirmation_id,'submitted_at':now,'status':state,'broker_order_id':str(result.get('broker_order_id') or result.get('order_id') or ''),'broker_result':result,'gates':g,'human_confirmed':True,'automatic_execution':False}; ih=_hash(body)
 with _conn() as c:
  c.execute('INSERT INTO execution_submissions VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,intent_id,confirmation_id,now,state,body['broker_order_id'],_json(body),SCHEMA_VERSION,VERSION,ih)); c.execute('UPDATE execution_intents SET state=? WHERE intent_id=?',(state,intent_id))
 return {'ok':ok,'status':state,'submission_id':sid,'submission':body,'integrity_hash':ih,'production_effect':'BROKER_SUBMISSION' if ok else 'NONE'}

def history(limit=100):
 init_db()
 with _conn() as c:rows=c.execute('SELECT * FROM execution_intents ORDER BY created_at DESC LIMIT ?',(max(1,min(int(limit),1000)),)).fetchall()
 return [{**dict(r),'intent':json.loads(r['intent_json'])} for r in rows]

def status():
 init_db()
 with _conn() as c:n=c.execute('SELECT COUNT(*) n FROM execution_intents').fetchone()['n']
 return {'status':'READY','engine':'CONFIRMATION_GATED_EXECUTION','build_version':VERSION,'schema_version':SCHEMA_VERSION,'intent_count':n,
  'automatic_execution_enabled':False,'explicit_human_confirmation_required':True,'preview_required':True,'idempotency_required':True,
  'risk_gate_required':True,'tradeability_gate_required':True,'broker_sync_gate_required':True,
  'runtime_execution_enabled':os.getenv('APEX_CONFIRMATION_GATED_EXECUTION_ENABLED','false').lower()=='true','production_effect':'NONE'}

def dashboard(limit=20):return {'ok':True,'status':'READY','safety':status(),'recent_intents':history(limit)}
