"""APEX 16.8 — Broker-Synchronized Position State.

Read-only broker normalization and reconciliation. Accepts broker snapshots from
an adapter (E*TRADE sandbox/live or fixtures), stores immutable snapshots, and
compares broker state with APEX state. Never submits, replaces, cancels, or
modifies an order or position.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, sqlite3, uuid
from typing import Any
from . import institutional_governance as gov

VERSION='16.8.16.8'; SCHEMA_VERSION='apex.broker_sync.v1'
SYNC_STATES=('SYNCED','DRIFT_DETECTED','BROKER_UNAVAILABLE','APEX_STATE_UNAVAILABLE','PARTIAL')
ORDER_STATES=('OPEN','PARTIAL','FILLED','CANCELED','REJECTED','EXPIRED','UNKNOWN')

def _now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def _json(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def _hash(v): return hashlib.sha256(_json(v).encode()).hexdigest()
def _conn():
 c=sqlite3.connect(gov.DB_PATH); c.row_factory=sqlite3.Row; return c

def init_db():
 gov.init_db()
 with _conn() as c:
  c.executescript('''
  CREATE TABLE IF NOT EXISTS broker_sync_snapshots(
    snapshot_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, broker TEXT NOT NULL,
    observed_at TEXT NOT NULL, sync_state TEXT NOT NULL, snapshot_json TEXT NOT NULL,
    schema_version TEXT NOT NULL, engine_version TEXT NOT NULL,
    integrity_hash TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(account_id,broker,observed_at));
  CREATE INDEX IF NOT EXISTS idx_bss_account_time ON broker_sync_snapshots(account_id,broker,observed_at);
  CREATE TABLE IF NOT EXISTS broker_sync_discrepancies(
    discrepancy_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL, account_id TEXT NOT NULL,
    observed_at TEXT NOT NULL, severity TEXT NOT NULL, discrepancy_type TEXT NOT NULL,
    discrepancy_json TEXT NOT NULL, schema_version TEXT NOT NULL,
    engine_version TEXT NOT NULL, integrity_hash TEXT NOT NULL, created_at TEXT NOT NULL);
  ''')
 return {'ok':True,'schema_version':SCHEMA_VERSION,'build_version':VERSION}

def _num(v,d=0.0):
 try:return float(v)
 except Exception:return d

def _norm_symbol(v): return str(v or '').upper().replace(' ','')
def _norm_side(v):
 s=str(v or '').upper()
 return 'LONG' if s in ('LONG','BUY','BTO','BOT') else 'SHORT' if s in ('SHORT','SELL','STO','SLD') else s or 'UNKNOWN'

def normalize(payload:dict|None=None)->dict[str,Any]:
 p=payload or {}; account=p.get('account') if isinstance(p.get('account'),dict) else {}
 positions=p.get('positions') if isinstance(p.get('positions'),list) else []
 orders=p.get('orders') if isinstance(p.get('orders'),list) else []
 fills=p.get('fills') if isinstance(p.get('fills'),list) else []
 npos=[]
 for x in positions:
  if not isinstance(x,dict): continue
  qty=_num(x.get('quantity') or x.get('qty'))
  npos.append({'position_id':str(x.get('position_id') or x.get('id') or ''),'symbol':_norm_symbol(x.get('symbol')),'description':x.get('description'),'side':_norm_side(x.get('side') or ('LONG' if qty>=0 else 'SHORT')),'quantity':abs(qty),'average_price':_num(x.get('average_price') or x.get('cost_basis_price') or x.get('entry_price')),'market_price':_num(x.get('market_price') or x.get('mark_price') or x.get('last_price')),'market_value':_num(x.get('market_value')),'unrealized_pnl':_num(x.get('unrealized_pnl') or x.get('total_gain')),'asset_type':str(x.get('asset_type') or x.get('security_type') or 'UNKNOWN').upper(),'expiry':x.get('expiry'),'strike':x.get('strike'),'option_type':x.get('option_type')})
 norders=[]
 for x in orders:
  if not isinstance(x,dict): continue
  status=str(x.get('status') or 'UNKNOWN').upper(); status=status if status in ORDER_STATES else 'UNKNOWN'
  norders.append({'order_id':str(x.get('order_id') or x.get('id') or ''),'symbol':_norm_symbol(x.get('symbol')),'side':_norm_side(x.get('side') or x.get('action')),'quantity':_num(x.get('quantity') or x.get('qty')),'filled_quantity':_num(x.get('filled_quantity') or x.get('executed_quantity')),'limit_price':_num(x.get('limit_price')) or None,'stop_price':_num(x.get('stop_price')) or None,'status':status,'order_type':str(x.get('order_type') or x.get('type') or 'UNKNOWN').upper(),'submitted_at':x.get('submitted_at')})
 nfills=[]
 for x in fills:
  if not isinstance(x,dict): continue
  nfills.append({'fill_id':str(x.get('fill_id') or x.get('id') or ''),'order_id':str(x.get('order_id') or ''),'symbol':_norm_symbol(x.get('symbol')),'side':_norm_side(x.get('side') or x.get('action')),'quantity':_num(x.get('quantity') or x.get('qty')),'price':_num(x.get('price') or x.get('fill_price')),'commission':_num(x.get('commission')),'filled_at':x.get('filled_at')})
 return {'broker':str(p.get('broker') or 'ETRADE').upper(),'account_id':str(p.get('account_id') or account.get('account_id') or 'PRIMARY'),'observed_at':str(p.get('observed_at') or _now()),'account':{'account_value':_num(account.get('account_value') or account.get('net_account_value')),'cash_available':_num(account.get('cash_available') or account.get('cash_balance')),'buying_power':_num(account.get('buying_power') or account.get('margin_buying_power')),'option_buying_power':_num(account.get('option_buying_power')),'day_trading_buying_power':_num(account.get('day_trading_buying_power'))},'positions':npos,'orders':norders,'fills':nfills,'source_status':str(p.get('source_status') or 'CONNECTED').upper(),'read_only':True}

def reconcile(payload:dict|None=None)->dict[str,Any]:
 p=payload or {}; broker=normalize(p.get('broker_snapshot') if isinstance(p.get('broker_snapshot'),dict) else p)
 apex=p.get('apex_state') if isinstance(p.get('apex_state'),dict) else {}
 discrepancies=[]
 if broker['source_status'] not in ('CONNECTED','HEALTHY','READY'):
  state='BROKER_UNAVAILABLE'; discrepancies.append({'type':'BROKER_SOURCE_UNAVAILABLE','severity':'BLOCKING','detail':broker['source_status']})
 elif not apex:
  state='APEX_STATE_UNAVAILABLE'
 else:
  apos=apex.get('positions') if isinstance(apex.get('positions'),list) else ([apex.get('position')] if isinstance(apex.get('position'),dict) and apex.get('position') else [])
  bmap={(_norm_symbol(x.get('symbol')),_norm_side(x.get('side'))):x for x in broker['positions']}
  amap={(_norm_symbol(x.get('symbol')),_norm_side(x.get('side'))):x for x in apos if isinstance(x,dict)}
  for key,b in bmap.items():
   a=amap.get(key)
   if not a: discrepancies.append({'type':'BROKER_POSITION_MISSING_IN_APEX','severity':'HIGH','symbol':key[0],'side':key[1],'broker_quantity':b['quantity']}); continue
   aq=abs(_num(a.get('quantity') or a.get('qty')))
   if abs(aq-b['quantity'])>1e-9: discrepancies.append({'type':'POSITION_QUANTITY_MISMATCH','severity':'HIGH','symbol':key[0],'broker_quantity':b['quantity'],'apex_quantity':aq})
   ap=_num(a.get('entry_price') or a.get('average_price'))
   if ap and b['average_price'] and abs(ap-b['average_price'])>0.01: discrepancies.append({'type':'COST_BASIS_MISMATCH','severity':'MEDIUM','symbol':key[0],'broker_average_price':b['average_price'],'apex_entry_price':ap})
  for key,a in amap.items():
   if key not in bmap: discrepancies.append({'type':'APEX_POSITION_MISSING_AT_BROKER','severity':'BLOCKING','symbol':key[0],'side':key[1],'apex_quantity':abs(_num(a.get('quantity') or a.get('qty')))})
  state='SYNCED' if not discrepancies else 'DRIFT_DETECTED'
 out={'status':'READY','sync_state':state,'broker_snapshot':broker,'discrepancies':discrepancies,'discrepancy_count':len(discrepancies),'blocking_discrepancy_count':sum(1 for x in discrepancies if x['severity']=='BLOCKING'),'position_count':len(broker['positions']),'open_order_count':sum(1 for x in broker['orders'] if x['status'] in ('OPEN','PARTIAL')),'fill_count':len(broker['fills']),'read_only':True,'broker_order_submission_enabled':False,'broker_order_cancel_enabled':False,'broker_order_replace_enabled':False,'position_mutation_enabled':False,'production_effect':'NONE'}
 out['integrity_hash']=_hash(out); return out

def record(payload:dict,actor='API'):
 init_db(); out=reconcile(payload); b=out['broker_snapshot']; aid=b['account_id']; broker=b['broker']; obs=b['observed_at']
 with _conn() as c:r=c.execute('SELECT * FROM broker_sync_snapshots WHERE account_id=? AND broker=? AND observed_at=?',(aid,broker,obs)).fetchone()
 if r:return {'ok':True,'status':'IMMUTABLE_EXISTS','created':False,'snapshot_id':r['snapshot_id'],'snapshot':json.loads(r['snapshot_json']),'integrity_hash':r['integrity_hash'],'production_effect':'NONE'}
 sid=str(uuid.uuid4()); body={**out,'recorded_by':actor}; ih=_hash(body); now=_now()
 with _conn() as c:
  c.execute('INSERT INTO broker_sync_snapshots VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,aid,broker,obs,out['sync_state'],_json(body),SCHEMA_VERSION,VERSION,ih,now))
  for d in out['discrepancies']:
   did=str(uuid.uuid4()); dih=_hash(d); c.execute('INSERT INTO broker_sync_discrepancies VALUES(?,?,?,?,?,?,?,?,?,?,?)',(did,sid,aid,obs,d['severity'],d['type'],_json(d),SCHEMA_VERSION,VERSION,dih,now))
 return {'ok':True,'status':'CREATED','created':True,'snapshot_id':sid,'snapshot':body,'integrity_hash':ih,'production_effect':'NONE'}

def latest(account_id='PRIMARY',broker='ETRADE'):
 init_db()
 with _conn() as c:r=c.execute('SELECT * FROM broker_sync_snapshots WHERE account_id=? AND broker=? ORDER BY observed_at DESC LIMIT 1',(account_id,broker)).fetchone()
 if not r:return {'ok':True,'status':'NO_DATA','sync_state':'BROKER_UNAVAILABLE','account_id':account_id,'broker':broker,'read_only':True,'production_effect':'NONE'}
 return {'ok':True,'status':'READY','snapshot_id':r['snapshot_id'],**json.loads(r['snapshot_json'])}

def history(account_id='PRIMARY',limit=100):
 init_db()
 with _conn() as c:rows=c.execute('SELECT * FROM broker_sync_snapshots WHERE account_id=? ORDER BY observed_at DESC LIMIT ?',(account_id,max(1,min(int(limit),1000)))).fetchall()
 return [{**dict(r),'snapshot':json.loads(r['snapshot_json'])} for r in rows]

def status():
 init_db()
 with _conn() as c:n=c.execute('SELECT COUNT(*) n FROM broker_sync_snapshots').fetchone()['n']
 return {'status':'READY','engine':'BROKER_SYNCHRONIZED_POSITION_STATE','build_version':VERSION,'schema_version':SCHEMA_VERSION,'supported_brokers':['ETRADE'],'snapshot_count':n,'read_only':True,'broker_order_submission_enabled':False,'broker_order_cancel_enabled':False,'broker_order_replace_enabled':False,'position_mutation_enabled':False,'production_effect':'NONE'}

def dashboard(account_id='PRIMARY',broker='ETRADE'): return {'ok':True,'status':'READY','safety':status(),'latest':latest(account_id,broker)}
