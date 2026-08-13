"""APEX 17.0 — Institutional Autonomous Desk.

Governed orchestration of the full trade lifecycle. Analysis and monitoring may be
automated, but broker submission still requires the existing 16.9 explicit human
confirmation boundary. This module never calls a broker directly.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, sqlite3, uuid
from typing import Any
from . import institutional_governance as gov

VERSION='17.0.17.0'; SCHEMA_VERSION='apex.autonomous_desk.v1'
STATES=('MONITORING','SETUP_DETECTED','VALIDATING','BLOCKED','READY_FOR_PREVIEW','AWAITING_CONFIRMATION','AUTHORIZED','SUBMITTED','PARTIALLY_FILLED','FILLED','MANAGING','PROTECTING','EXIT_PENDING','CLOSED','RECONCILED','GRADED')
TERMINAL_STATES=('BLOCKED','GRADED')
TRANSITIONS={
 'MONITORING':('SETUP_DETECTED',), 'SETUP_DETECTED':('VALIDATING','BLOCKED'),
 'VALIDATING':('BLOCKED','READY_FOR_PREVIEW'), 'READY_FOR_PREVIEW':('AWAITING_CONFIRMATION','BLOCKED'),
 'AWAITING_CONFIRMATION':('AUTHORIZED','BLOCKED'), 'AUTHORIZED':('SUBMITTED','BLOCKED'),
 'SUBMITTED':('PARTIALLY_FILLED','FILLED','BLOCKED'), 'PARTIALLY_FILLED':('FILLED','EXIT_PENDING','BLOCKED'),
 'FILLED':('MANAGING','EXIT_PENDING'), 'MANAGING':('PROTECTING','EXIT_PENDING'),
 'PROTECTING':('MANAGING','EXIT_PENDING'), 'EXIT_PENDING':('CLOSED','BLOCKED'),
 'CLOSED':('RECONCILED',), 'RECONCILED':('GRADED',), 'BLOCKED':('VALIDATING',)
}

def _now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def _json(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def _hash(v): return hashlib.sha256(_json(v).encode()).hexdigest()
def _conn():
 c=sqlite3.connect(gov.DB_PATH); c.row_factory=sqlite3.Row; return c

def init_db():
 gov.init_db()
 with _conn() as c:
  c.executescript('''
  CREATE TABLE IF NOT EXISTS autonomous_desk_trades(
   desk_trade_id TEXT PRIMARY KEY,idempotency_key TEXT NOT NULL UNIQUE,symbol TEXT NOT NULL,
   state TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,trade_json TEXT NOT NULL,
   schema_version TEXT NOT NULL,engine_version TEXT NOT NULL,integrity_hash TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS autonomous_desk_events(
   event_id TEXT PRIMARY KEY,desk_trade_id TEXT NOT NULL,sequence_no INTEGER NOT NULL,
   from_state TEXT,to_state TEXT NOT NULL,event_type TEXT NOT NULL,actor TEXT NOT NULL,
   observed_at TEXT NOT NULL,event_json TEXT NOT NULL,schema_version TEXT NOT NULL,
   engine_version TEXT NOT NULL,integrity_hash TEXT NOT NULL,UNIQUE(desk_trade_id,sequence_no));
  CREATE TABLE IF NOT EXISTS autonomous_desk_artifacts(
   artifact_id TEXT PRIMARY KEY,desk_trade_id TEXT NOT NULL,artifact_type TEXT NOT NULL,
   external_id TEXT,observed_at TEXT NOT NULL,artifact_json TEXT NOT NULL,
   schema_version TEXT NOT NULL,engine_version TEXT NOT NULL,integrity_hash TEXT NOT NULL,
   UNIQUE(desk_trade_id,artifact_type,external_id));
  ''')
 return {'ok':True,'schema_version':SCHEMA_VERSION,'build_version':VERSION}

def _blocking(snapshot:dict)->list[str]:
 blocks=[]
 live=snapshot.get('live_operations') if isinstance(snapshot.get('live_operations'),dict) else {}
 risk=snapshot.get('portfolio_risk') if isinstance(snapshot.get('portfolio_risk'),dict) else {}
 broker=snapshot.get('broker_sync') if isinstance(snapshot.get('broker_sync'),dict) else {}
 if str(snapshot.get('tradeability') or live.get('tradeability') or 'NOT_TRADEABLE').upper() not in ('TRADEABLE','TRADEABLE_WITH_CAUTION'): blocks.append('TRADEABILITY_BLOCK')
 if risk and str(risk.get('risk_state') or '').upper() in ('BREACH','LOCKED_OUT'): blocks.append('RISK_STATE_BLOCK')
 if risk and not bool((risk.get('permissions') or {}).get('new_entries_allowed',risk.get('new_entries_allowed',False))): blocks.append('RISK_PERMISSION_BLOCK')
 if broker and str(broker.get('sync_state') or '').upper() not in ('SYNCED','PARTIAL'): blocks.append('BROKER_SYNC_BLOCK')
 if int(broker.get('blocking_discrepancy_count') or 0)>0: blocks.append('BROKER_DISCREPANCY_BLOCK')
 if not snapshot.get('setup') and not snapshot.get('recommendation_id'): blocks.append('SETUP_REQUIRED')
 return blocks

def create_trade(payload:dict, idempotency_key:str|None=None)->dict[str,Any]:
 init_db(); symbol=str(payload.get('symbol') or 'SPX').upper(); key=str(idempotency_key or payload.get('idempotency_key') or _hash(payload))
 with _conn() as c:r=c.execute('SELECT * FROM autonomous_desk_trades WHERE idempotency_key=?',(key,)).fetchone()
 if r:return {'ok':True,'status':'IMMUTABLE_EXISTS','created':False,'desk_trade_id':r['desk_trade_id'],'trade':json.loads(r['trade_json']),'integrity_hash':r['integrity_hash']}
 tid=str(uuid.uuid4()); now=_now(); body={'desk_trade_id':tid,'idempotency_key':key,'symbol':symbol,'state':'MONITORING','recommendation_id':str(payload.get('recommendation_id') or ''),'setup':payload.get('setup') if isinstance(payload.get('setup'),dict) else {},'strategy':str(payload.get('strategy') or ''),'account_id':str(payload.get('account_id') or 'PRIMARY'),'created_by':str(payload.get('actor') or 'API'),'links':{},'management':{},'outcome':{},'created_at':now,'updated_at':now}; ih=_hash(body)
 with _conn() as c:
  c.execute('INSERT INTO autonomous_desk_trades VALUES(?,?,?,?,?,?,?,?,?,?)',(tid,key,symbol,'MONITORING',now,now,_json(body),SCHEMA_VERSION,VERSION,ih))
  _insert_event(c,tid,0,'','MONITORING','TRADE_CREATED',body['created_by'],{'trade':body},now)
 return {'ok':True,'status':'CREATED','created':True,'desk_trade_id':tid,'trade':body,'integrity_hash':ih,'production_effect':'NONE'}

def _insert_event(c,tid,seq,frm,to,event_type,actor,evidence,when=None):
 body={'desk_trade_id':tid,'sequence_no':seq,'from_state':frm,'to_state':to,'event_type':event_type,'actor':actor,'observed_at':when or _now(),'evidence':evidence}; ih=_hash(body)
 c.execute('INSERT INTO autonomous_desk_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),tid,seq,frm,to,event_type,actor,body['observed_at'],_json(body),SCHEMA_VERSION,VERSION,ih))
 return body

def get_trade(tid:str)->dict|None:
 init_db()
 with _conn() as c:r=c.execute('SELECT * FROM autonomous_desk_trades WHERE desk_trade_id=?',(tid,)).fetchone()
 return None if not r else {**json.loads(r['trade_json']),'integrity_hash':r['integrity_hash']}

def transition(tid:str,to_state:str,evidence:dict|None=None,actor='SYSTEM')->dict[str,Any]:
 init_db(); target=str(to_state or '').upper()
 if target not in STATES:return {'ok':False,'status':'INVALID_STATE','allowed_states':list(STATES)}
 with _conn() as c:
  r=c.execute('SELECT * FROM autonomous_desk_trades WHERE desk_trade_id=?',(tid,)).fetchone()
  if not r:return {'ok':False,'status':'NOT_FOUND'}
  current=r['state']; allowed=TRANSITIONS.get(current,())
  if target not in allowed:return {'ok':False,'status':'INVALID_TRANSITION','from_state':current,'to_state':target,'allowed':list(allowed)}
  ev=evidence if isinstance(evidence,dict) else {}
  if target=='READY_FOR_PREVIEW':
   blocks=_blocking(ev)
   if blocks:return {'ok':False,'status':'BLOCKED','blocking_reasons':blocks,'recommended_state':'BLOCKED','production_effect':'NONE'}
  if target=='AUTHORIZED' and not (ev.get('confirmation_id') and ev.get('confirmed_by') and ev.get('explicit_acknowledgement')):return {'ok':False,'status':'CONFIRMATION_REQUIRED','production_effect':'NONE'}
  if target=='SUBMITTED' and not ev.get('broker_order_id'):return {'ok':False,'status':'BROKER_ORDER_ID_REQUIRED'}
  if target in ('CLOSED','RECONCILED') and not ev.get('broker_flat',False):return {'ok':False,'status':'BROKER_FLAT_REQUIRED'}
  body=json.loads(r['trade_json']); now=_now(); body['state']=target; body['updated_at']=now
  links=body.setdefault('links',{})
  for k in ('intent_id','preview_record_id','confirmation_id','submission_id','broker_order_id','broker_sync_snapshot_id'): 
   if ev.get(k): links[k]=ev[k]
  if ev.get('management'):body['management']=ev['management']
  if ev.get('outcome'):body['outcome']=ev['outcome']
  ih=_hash(body); seq=c.execute('SELECT COALESCE(MAX(sequence_no),-1)+1 n FROM autonomous_desk_events WHERE desk_trade_id=?',(tid,)).fetchone()['n']
  _insert_event(c,tid,seq,current,target,str(ev.get('event_type') or 'STATE_TRANSITION'),str(actor or 'SYSTEM'),ev,now)
  c.execute('UPDATE autonomous_desk_trades SET state=?,updated_at=?,trade_json=?,integrity_hash=? WHERE desk_trade_id=?',(target,now,_json(body),ih,tid))
 return {'ok':True,'status':'TRANSITIONED','desk_trade_id':tid,'from_state':current,'to_state':target,'trade':body,'integrity_hash':ih,'production_effect':'NONE'}

def attach_artifact(tid:str,artifact_type:str,payload:dict,external_id:str='')->dict[str,Any]:
 init_db(); typ=str(artifact_type or '').upper()
 if not get_trade(tid):return {'ok':False,'status':'NOT_FOUND'}
 key=str(external_id or _hash(payload)); now=_now(); body={'desk_trade_id':tid,'artifact_type':typ,'external_id':key,'observed_at':now,'payload':payload}; ih=_hash(body)
 with _conn() as c:
  r=c.execute('SELECT * FROM autonomous_desk_artifacts WHERE desk_trade_id=? AND artifact_type=? AND external_id=?',(tid,typ,key)).fetchone()
  if r:return {'ok':True,'status':'IMMUTABLE_EXISTS','artifact_id':r['artifact_id'],'integrity_hash':r['integrity_hash']}
  aid=str(uuid.uuid4()); c.execute('INSERT INTO autonomous_desk_artifacts VALUES(?,?,?,?,?,?,?,?,?)',(aid,tid,typ,key,now,_json(body),SCHEMA_VERSION,VERSION,ih))
 return {'ok':True,'status':'RECORDED','created':True,'artifact_id':aid,'integrity_hash':ih,'production_effect':'NONE'}

def timeline(tid:str)->dict[str,Any]:
 init_db(); trade=get_trade(tid)
 if not trade:return {'ok':False,'status':'NOT_FOUND','events':[],'artifacts':[]}
 with _conn() as c:
  events=[json.loads(r['event_json']) for r in c.execute('SELECT * FROM autonomous_desk_events WHERE desk_trade_id=? ORDER BY sequence_no',(tid,)).fetchall()]
  artifacts=[json.loads(r['artifact_json']) for r in c.execute('SELECT * FROM autonomous_desk_artifacts WHERE desk_trade_id=? ORDER BY observed_at',(tid,)).fetchall()]
 return {'ok':True,'status':'READY','trade':trade,'events':events,'artifacts':artifacts}

def history(limit=50,state:str|None=None):
 init_db(); q='SELECT * FROM autonomous_desk_trades'; args=[]
 if state:q+=' WHERE state=?'; args.append(str(state).upper())
 q+=' ORDER BY updated_at DESC LIMIT ?'; args.append(max(1,min(int(limit),500)))
 with _conn() as c:rows=c.execute(q,args).fetchall()
 return [{**json.loads(r['trade_json']),'integrity_hash':r['integrity_hash']} for r in rows]

def status():
 init_db()
 with _conn() as c:n=c.execute('SELECT COUNT(*) n FROM autonomous_desk_trades').fetchone()['n']
 return {'status':'READY','engine':'INSTITUTIONAL_AUTONOMOUS_DESK','build_version':VERSION,'schema_version':SCHEMA_VERSION,'trade_count':n,'autonomous_analysis_enabled':True,'autonomous_monitoring_enabled':True,'autonomous_management_recommendations_enabled':True,'automatic_order_submission_enabled':False,'human_confirmation_required':True,'broker_mutation_enabled':False,'production_effect':'NONE'}

def dashboard(limit=12):
 xs=history(limit); active=[x for x in xs if x.get('state') not in TERMINAL_STATES]
 return {'ok':True,'status':'READY','safety':status(),'active_trades':active,'recent_trades':xs,'state_model':list(STATES)}
