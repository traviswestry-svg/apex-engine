"""APEX 13 Sprint 9A: production promotion governance.

This module creates immutable promotion records and manifests. It cannot activate,
deploy, or mutate production configuration.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, sqlite3, uuid
from typing import Any, Mapping
from . import institutional_governance as gov
from . import shadow_validation

VERSION='13.0.9A'
SCHEMA_VERSION='apex.production.governance.v1'
REQUIRED_ROLES=('SYSTEM_ARCHITECTURE','TRADING_LOGIC','RISK_CONTROLS')

def _now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def _json(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def _load(v,default=None):
    try:return json.loads(v) if v not in (None,'') else ({} if default is None else default)
    except Exception:return {} if default is None else default

def _conn():
    c=sqlite3.connect(gov.DB_PATH); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c

def init_db():
    gov.init_db(); shadow_validation.init_db()
    with _conn() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS production_versions(
          production_version_id TEXT PRIMARY KEY,domain TEXT NOT NULL,version TEXT NOT NULL,parent_version_id TEXT,
          source_candidate_id TEXT,source_package_id TEXT,created_at TEXT NOT NULL,created_by TEXT NOT NULL,
          config_json TEXT NOT NULL,metadata_json TEXT NOT NULL,integrity_hash TEXT NOT NULL,status TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_prod_domain_version ON production_versions(domain,version);
        CREATE TABLE IF NOT EXISTS production_promotion_requests(
          promotion_id TEXT PRIMARY KEY,domain TEXT NOT NULL,candidate_id TEXT NOT NULL,package_id TEXT NOT NULL,
          current_champion_version TEXT NOT NULL,proposed_version TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,
          created_by TEXT NOT NULL,queued_at TEXT,rejected_at TEXT,rejection_reason TEXT,release_notes TEXT NOT NULL,
          rollback_target TEXT NOT NULL,metadata_json TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_promotion_package ON production_promotion_requests(package_id);
        CREATE TABLE IF NOT EXISTS production_approvals(
          approval_id TEXT PRIMARY KEY,promotion_id TEXT NOT NULL,role TEXT NOT NULL,decision TEXT NOT NULL,actor TEXT NOT NULL,
          decided_at TEXT NOT NULL,note TEXT NOT NULL,evidence_json TEXT NOT NULL,
          FOREIGN KEY(promotion_id) REFERENCES production_promotion_requests(promotion_id));
        CREATE UNIQUE INDEX IF NOT EXISTS idx_promotion_role ON production_approvals(promotion_id,role);
        CREATE TABLE IF NOT EXISTS production_manifests(
          manifest_id TEXT PRIMARY KEY,promotion_id TEXT NOT NULL,created_at TEXT NOT NULL,manifest_json TEXT NOT NULL,
          integrity_hash TEXT NOT NULL,status TEXT NOT NULL,FOREIGN KEY(promotion_id) REFERENCES production_promotion_requests(promotion_id));
        CREATE UNIQUE INDEX IF NOT EXISTS idx_manifest_promotion ON production_manifests(promotion_id);
        CREATE TABLE IF NOT EXISTS production_rollback_targets(
          rollback_id TEXT PRIMARY KEY,promotion_id TEXT NOT NULL,target_version TEXT NOT NULL,created_at TEXT NOT NULL,
          created_by TEXT NOT NULL,reason TEXT NOT NULL,metadata_json TEXT NOT NULL,
          FOREIGN KEY(promotion_id) REFERENCES production_promotion_requests(promotion_id));
        ''')
    return {'ok':True,'schema_version':SCHEMA_VERSION}

def _row(table,key,value):
    init_db()
    with _conn() as c:r=c.execute(f'SELECT * FROM {table} WHERE {key}=?',(value,)).fetchone()
    return dict(r) if r else None

def promotion(promotion_id):
    d=_row('production_promotion_requests','promotion_id',promotion_id)
    if d:d['metadata']=_load(d.pop('metadata_json'))
    return d

def _package(package_id):
    init_db()
    with _conn() as c:r=c.execute('SELECT * FROM promotion_review_packages WHERE package_id=?',(package_id,)).fetchone()
    return dict(r) if r else None

def create_promotion(payload:Mapping[str,Any],actor='API'):
    init_db(); package_id=str(payload.get('package_id') or '').strip(); pkg=_package(package_id)
    if not pkg:return {'ok':False,'status':'UNAVAILABLE','error':'promotion review package not found'}
    if pkg['disposition']!='ELIGIBLE_FOR_PRODUCTION_REVIEW':return {'ok':False,'status':'APPROVAL_REQUIRED','error':'package is not eligible for production review'}
    candidate_id=pkg['candidate_id']; domain=str(payload.get('domain') or 'decision_weights')
    cc=shadow_validation.champion_challenger(domain); champion=str(payload.get('current_champion_version') or cc.get('champion',{}).get('champion_version') or 'PRODUCTION_CURRENT')
    proposed=str(payload.get('proposed_version') or f"candidate-{candidate_id[:8]}"); pid=str(uuid.uuid4())
    try:
        with _conn() as c:c.execute('INSERT INTO production_promotion_requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(pid,domain,candidate_id,package_id,champion,proposed,'PENDING_REVIEW',_now(),actor,None,None,None,str(payload.get('release_notes') or ''),champion,_json({'production_effect':'NONE','required_roles':REQUIRED_ROLES,'automatic_activation':False})))
    except sqlite3.IntegrityError:return {'ok':False,'status':'APPROVAL_REQUIRED','error':'promotion already exists for package'}
    with _conn() as c:c.execute('INSERT INTO production_rollback_targets VALUES(?,?,?,?,?,?,?)',(str(uuid.uuid4()),pid,champion,_now(),actor,'Automatic rollback target captured at request creation',_json({'immutable':True})))
    gov.audit('CREATE_PRODUCTION_PROMOTION','production_promotion',pid,new={'package_id':package_id,'candidate_id':candidate_id,'proposed_version':proposed},actor=actor)
    return {'ok':True,'status':'PENDING_REVIEW','promotion_id':pid,'production_effect':'NONE'}

def approvals(promotion_id):
    init_db()
    with _conn() as c:rows=c.execute('SELECT * FROM production_approvals WHERE promotion_id=? ORDER BY decided_at',(promotion_id,)).fetchall()
    return [dict(r) | {'evidence':_load(r['evidence_json'])} for r in rows]

def decide(promotion_id,role,decision,actor='API',note='',evidence=None):
    p=promotion(promotion_id)
    if not p:return {'ok':False,'status':'UNAVAILABLE','error':'promotion not found'}
    role=str(role).upper(); decision=str(decision).upper()
    if role not in REQUIRED_ROLES:return {'ok':False,'status':'UNAVAILABLE','error':'invalid approval role'}
    if decision not in {'APPROVE','REJECT'}:return {'ok':False,'status':'UNAVAILABLE','error':'invalid decision'}
    if p['status'] not in {'PENDING_REVIEW','PARTIALLY_APPROVED'}:return {'ok':False,'status':'APPROVAL_REQUIRED','error':'promotion is not reviewable'}
    try:
        with _conn() as c:c.execute('INSERT INTO production_approvals VALUES(?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),promotion_id,role,decision,actor,_now(),note,_json(evidence or {})))
    except sqlite3.IntegrityError:return {'ok':False,'status':'APPROVAL_REQUIRED','error':'role already decided'}
    if decision=='REJECT': new='REJECTED'
    else:
        approved={x['role'] for x in approvals(promotion_id) if x['decision']=='APPROVE'}
        new='APPROVED_FOR_QUEUE' if set(REQUIRED_ROLES)<=approved else 'PARTIALLY_APPROVED'
    with _conn() as c:c.execute('UPDATE production_promotion_requests SET status=?,rejected_at=?,rejection_reason=? WHERE promotion_id=?',(new,_now() if new=='REJECTED' else None,note if new=='REJECTED' else None,promotion_id))
    gov.audit('PRODUCTION_PROMOTION_DECISION','production_promotion',promotion_id,previous={'status':p['status']},new={'status':new,'role':role,'decision':decision},actor=actor,explanation=note)
    return {'ok':True,'status':new,'promotion_id':promotion_id,'production_effect':'NONE'}

def queue(promotion_id,actor='API'):
    p=promotion(promotion_id)
    if not p:return {'ok':False,'status':'UNAVAILABLE','error':'promotion not found'}
    if p['status']!='APPROVED_FOR_QUEUE':return {'ok':False,'status':'APPROVAL_REQUIRED','error':'all required approvals are not complete'}
    manifest={'schema_version':SCHEMA_VERSION,'promotion_id':promotion_id,'candidate_id':p['candidate_id'],'review_package_id':p['package_id'],'current_champion_version':p['current_champion_version'],'proposed_version':p['proposed_version'],'rollback_target':p['rollback_target'],'approvals':approvals(promotion_id),'release_notes':p['release_notes'],'queued_at':_now(),'production_effect':'NONE','automatic_activation':False}
    raw=_json(manifest); h=hashlib.sha256(raw.encode()).hexdigest(); mid=str(uuid.uuid4())
    with _conn() as c:
        c.execute('INSERT INTO production_manifests VALUES(?,?,?,?,?,?)',(mid,promotion_id,_now(),raw,h,'QUEUED_NOT_DEPLOYED'))
        c.execute('UPDATE production_promotion_requests SET status=?,queued_at=? WHERE promotion_id=?',('QUEUED_NOT_DEPLOYED',_now(),promotion_id))
    gov.audit('QUEUE_PRODUCTION_PROMOTION','production_promotion',promotion_id,previous={'status':p['status']},new={'status':'QUEUED_NOT_DEPLOYED','manifest_id':mid},actor=actor)
    return {'ok':True,'status':'QUEUED_NOT_DEPLOYED','promotion_id':promotion_id,'manifest_id':mid,'integrity_hash':h,'production_effect':'NONE'}

def list_promotions(limit=100):
    init_db()
    with _conn() as c:rows=c.execute('SELECT * FROM production_promotion_requests ORDER BY created_at DESC LIMIT ?',(max(1,min(limit,1000)),)).fetchall()
    return [dict(r) | {'metadata':_load(r['metadata_json'])} for r in rows]

def manifests(limit=100):
    init_db()
    with _conn() as c:rows=c.execute('SELECT * FROM production_manifests ORDER BY created_at DESC LIMIT ?',(max(1,min(limit,1000)),)).fetchall()
    return [dict(r) | {'manifest':_load(r['manifest_json'])} for r in rows]

def rollback_targets(limit=100):
    init_db()
    with _conn() as c:rows=c.execute('SELECT * FROM production_rollback_targets ORDER BY created_at DESC LIMIT ?',(max(1,min(limit,1000)),)).fetchall()
    return [dict(r) | {'metadata':_load(r['metadata_json'])} for r in rows]

def status(domain='decision_weights'):
    ps=list_promotions(1000); cc=shadow_validation.champion_challenger(domain)
    return {'schema_version':SCHEMA_VERSION,'status':'READY','current_champion':cc.get('champion'),'promotion_count':len(ps),'pending_count':sum(1 for p in ps if p['status'] in {'PENDING_REVIEW','PARTIALLY_APPROVED','APPROVED_FOR_QUEUE'}),'queued_not_deployed':sum(1 for p in ps if p['status']=='QUEUED_NOT_DEPLOYED'),'required_roles':list(REQUIRED_ROLES),'automatic_activation':False,'production_mutation_enabled':False,'production_effect':'NONE','build_version':VERSION}
