"""APEX 13.0 Sprint 1 immutable institutional evidence case files."""
from __future__ import annotations
import datetime as dt, hashlib, json, os, sqlite3, uuid
from typing import Any, Dict, Mapping, Optional
from . import recommendation_ledger as ledger

VERSION='13.0.0-sprint1'; SCHEMA_VERSION=1
DB_PATH=os.getenv('APEX_EVIDENCE_DB', os.path.join(os.path.dirname(os.path.dirname(__file__)),'apex_evidence.db'))
STATUS={'READY','INCOMPLETE','UNAVAILABLE','COLLECTING'}

def _now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def _json(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def _load(v,d=None):
    try: return json.loads(v) if v else ({} if d is None else d)
    except Exception: return {} if d is None else d
def _hash(v): return hashlib.sha256(_json(v).encode()).hexdigest()
def _conn():
    os.makedirs(os.path.dirname(DB_PATH) or '.',exist_ok=True)
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA journal_mode=WAL'); return c

def init_db():
    with _conn() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS evidence_schema(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS evidence_packages(
          package_id TEXT PRIMARY KEY,recommendation_id TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,
          schema_version TEXT NOT NULL,build_version TEXT NOT NULL,status TEXT NOT NULL,
          package_json TEXT NOT NULL,integrity_hash TEXT NOT NULL,finalized_at TEXT);
        CREATE INDEX IF NOT EXISTS idx_ev_pkg_status ON evidence_packages(status,created_at);
        CREATE TABLE IF NOT EXISTS evidence_snapshots(
          snapshot_id TEXT PRIMARY KEY,recommendation_id TEXT NOT NULL,snapshot_type TEXT NOT NULL,
          captured_at TEXT NOT NULL,payload_json TEXT NOT NULL,provenance_json TEXT NOT NULL,
          integrity_hash TEXT NOT NULL,UNIQUE(recommendation_id,snapshot_type,integrity_hash));
        CREATE INDEX IF NOT EXISTS idx_ev_snap_rec ON evidence_snapshots(recommendation_id,captured_at);
        CREATE TABLE IF NOT EXISTS evidence_timeline(
          sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT NOT NULL UNIQUE,recommendation_id TEXT NOT NULL,
          event_at TEXT NOT NULL,event_type TEXT NOT NULL,previous_json TEXT NOT NULL,new_json TEXT NOT NULL,
          evidence_json TEXT NOT NULL,explanation TEXT NOT NULL,source TEXT NOT NULL,provenance_json TEXT NOT NULL,
          build_version TEXT NOT NULL,integrity_hash TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_ev_timeline_rec ON evidence_timeline(recommendation_id,sequence_id);
        CREATE TABLE IF NOT EXISTS evidence_integrity_results(
          result_id TEXT PRIMARY KEY,recommendation_id TEXT NOT NULL,checked_at TEXT NOT NULL,status TEXT NOT NULL,
          checks_json TEXT NOT NULL,missing_json TEXT NOT NULL,integrity_hash TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_ev_integrity_rec ON evidence_integrity_results(recommendation_id,checked_at);
        ''')
        c.execute('INSERT OR IGNORE INTO evidence_schema VALUES(?,?)',(SCHEMA_VERSION,_now()))
    return {'ok':True,'schema_version':SCHEMA_VERSION,'db_path':DB_PATH}

def _canonical_from_ledger(rec:Mapping[str,Any])->Dict[str,Any]:
    snap=rec.get('snapshot') or {}; inst=snap.get('institutional_decision') or snap.get('canonical_decision') or {}
    return {
      'recommendation_id':rec.get('recommendation_id'),'timestamp':rec.get('captured_at'),'ticker':rec.get('ticker'),
      'strategy':rec.get('strategy'),'status':rec.get('state'),'confidence':rec.get('final_live_confidence'),
      'market_narrative':inst.get('market_narrative') or snap.get('narrative') or {},
      'primary_thesis':inst.get('primary_thesis'),'alternate_thesis':inst.get('alternate_thesis'),
      'institutional_consensus':inst.get('institutional_consensus') or {},'conviction':inst.get('conviction') or {},
      'confidence_attribution':inst.get('confidence_attribution') or {},'execution':inst.get('execution') or {},
      'position_quality':inst.get('position_quality') or {},'liquidity':inst.get('liquidity') or {},
      'provider_health':inst.get('provider_health') or snap.get('provider_health') or {},
      'data_freshness':inst.get('data_freshness') or snap.get('freshness') or {},
      'risks':inst.get('risks') or [],'invalidation':inst.get('invalidation') or {},
      'evidence':rec.get('evidence') or {},'provenance':{'ledger_schema_version':rec.get('ledger_schema_version'),'application_version':rec.get('application_version'),'build':rec.get('build'),'commit_sha':rec.get('commit_sha')},
      'lifecycle':rec.get('events') or []}

def build_package(recommendation_id:str)->Dict[str,Any]:
    rec=ledger.get_recommendation(recommendation_id)
    if not rec: return {'ok':False,'status':'UNAVAILABLE','error':'recommendation_not_found'}
    decision=_canonical_from_ledger(rec)
    pkg={'schema_version':'apex.evidence.package.v1','recommendation_id':recommendation_id,'captured_at':rec.get('captured_at'),'canonical_decision':decision,
         'snapshots':{'narrative':decision['market_narrative'],'consensus':decision['institutional_consensus'],'conviction':decision['conviction'],'confidence_attribution':decision['confidence_attribution'],'execution':decision['execution'],'position_quality':decision['position_quality'],'liquidity':decision['liquidity'],'provider_health':decision['provider_health'],'data_freshness':decision['data_freshness']},
         'versions':decision['provenance'],'provenance':decision['provenance'],'immutable':True,'build_version':VERSION}
    return {'ok':True,'status':'READY','package':pkg,'integrity_hash':_hash(pkg)}

def capture(recommendation_id:str)->Dict[str,Any]:
    init_db(); built=build_package(recommendation_id)
    if not built.get('ok'): return built
    pkg=built['package']; now=_now(); pid=str(uuid.uuid4())
    with _conn() as c:
        old=c.execute('SELECT * FROM evidence_packages WHERE recommendation_id=?',(recommendation_id,)).fetchone()
        if old: return {'ok':True,'status':old['status'],'created':False,'immutable':True,'package_id':old['package_id'],'integrity_hash':old['integrity_hash']}
        c.execute('INSERT INTO evidence_packages VALUES(?,?,?,?,?,?,?,?,?)',(pid,recommendation_id,now,'apex.evidence.package.v1',VERSION,'READY',_json(pkg),built['integrity_hash'],None))
        for typ,payload in pkg['snapshots'].items():
            h=_hash(payload); c.execute('INSERT OR IGNORE INTO evidence_snapshots VALUES(?,?,?,?,?,?,?)',(str(uuid.uuid4()),recommendation_id,typ.upper(),now,_json(payload),_json(pkg['provenance']),h))
    append_event(recommendation_id,'RECOMMENDATION_CREATED',new_state={'status':pkg['canonical_decision'].get('status')},evidence={'package_hash':built['integrity_hash']},explanation='Immutable institutional evidence package captured from the recommendation ledger.',source='EVIDENCE_BUILDER')
    integrity=validate(recommendation_id)
    return {'ok':True,'status':integrity['status'],'created':True,'package_id':pid,'integrity_hash':built['integrity_hash']}

def append_event(recommendation_id:str,event_type:str,*,previous_state:Optional[Mapping[str,Any]]=None,new_state:Optional[Mapping[str,Any]]=None,evidence:Optional[Mapping[str,Any]]=None,explanation:str='',source:str='SYSTEM',provenance:Optional[Mapping[str,Any]]=None,event_at:Optional[str]=None)->Dict[str,Any]:
    init_db(); at=event_at or _now(); body={'recommendation_id':recommendation_id,'event_at':at,'event_type':event_type.upper(),'previous_state':dict(previous_state or {}),'new_state':dict(new_state or {}),'triggering_evidence':dict(evidence or {}),'explanation':explanation,'source':source,'provenance':dict(provenance or {}),'build_version':VERSION}; h=_hash(body); eid=str(uuid.uuid4())
    with _conn() as c: c.execute('INSERT INTO evidence_timeline(event_id,recommendation_id,event_at,event_type,previous_json,new_json,evidence_json,explanation,source,provenance_json,build_version,integrity_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(eid,recommendation_id,at,body['event_type'],_json(body['previous_state']),_json(body['new_state']),_json(body['triggering_evidence']),explanation,source,_json(body['provenance']),VERSION,h))
    return {'ok':True,'event_id':eid,'integrity_hash':h}

def validate(recommendation_id:str)->Dict[str,Any]:
    init_db()
    with _conn() as c: row=c.execute('SELECT * FROM evidence_packages WHERE recommendation_id=?',(recommendation_id,)).fetchone()
    if not row: return {'ok':False,'status':'UNAVAILABLE','checks':{},'missing':['evidence_package']}
    pkg=_load(row['package_json']); required=['schema_version','recommendation_id','canonical_decision','snapshots','versions','provenance','build_version']; missing=[x for x in required if pkg.get(x) in (None,'',{})]
    checks={'package_hash_matches':_hash(pkg)==row['integrity_hash'],'recommendation_id_matches':pkg.get('recommendation_id')==recommendation_id,'schema_version_present':bool(pkg.get('schema_version')),'provenance_present':bool(pkg.get('provenance')),'immutable':pkg.get('immutable') is True}
    status='READY' if not missing and all(checks.values()) else 'INCOMPLETE'; result={'status':status,'checks':checks,'missing':missing,'checked_at':_now()}; h=_hash(result)
    with _conn() as c:
        c.execute('INSERT INTO evidence_integrity_results VALUES(?,?,?,?,?,?,?)',(str(uuid.uuid4()),recommendation_id,result['checked_at'],status,_json(checks),_json(missing),h)); c.execute('UPDATE evidence_packages SET status=? WHERE recommendation_id=?',(status,recommendation_id))
    return {'ok':status=='READY',**result,'integrity_hash':h}

def get(recommendation_id:str)->Optional[Dict[str,Any]]:
    init_db()
    with _conn() as c: row=c.execute('SELECT * FROM evidence_packages WHERE recommendation_id=?',(recommendation_id,)).fetchone()
    if not row: return None
    return {'package_id':row['package_id'],'recommendation_id':row['recommendation_id'],'created_at':row['created_at'],'schema_version':row['schema_version'],'build_version':row['build_version'],'status':row['status'],'integrity_hash':row['integrity_hash'],'finalized_at':row['finalized_at'],'package':_load(row['package_json'])}

def timeline(recommendation_id:str):
    init_db()
    with _conn() as c: rows=c.execute('SELECT * FROM evidence_timeline WHERE recommendation_id=? ORDER BY sequence_id',(recommendation_id,)).fetchall()
    return [{'sequence':r['sequence_id'],'event_id':r['event_id'],'timestamp':r['event_at'],'event_type':r['event_type'],'previous_state':_load(r['previous_json']),'new_state':_load(r['new_json']),'triggering_evidence':_load(r['evidence_json']),'explanation':r['explanation'],'source':r['source'],'provenance':_load(r['provenance_json']),'build_version':r['build_version'],'integrity_hash':r['integrity_hash']} for r in rows]

def metadata(recommendation_id:str):
    p=get(recommendation_id)
    if not p:return None
    return {k:p[k] for k in ('package_id','recommendation_id','created_at','schema_version','build_version','status','integrity_hash','finalized_at')}

def status():
    init_db()
    with _conn() as c:
        rows=c.execute('SELECT status,COUNT(*) n FROM evidence_packages GROUP BY status').fetchall(); total=sum(r['n'] for r in rows)
    return {'status':'COLLECTING' if total==0 else 'READY','total_packages':total,'by_status':{r['status']:r['n'] for r in rows},'schema_version':'apex.evidence.status.v1','build_version':VERSION}
