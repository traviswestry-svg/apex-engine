"""APEX 13 Sprint 9B: human-controlled canary deployment controller.

The controller never rewrites strategy code or configuration. It authorizes a
bounded challenger routing decision for explicitly eligible recommendations and
fails back to the recorded champion on any safety breach.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, sqlite3, uuid
from typing import Any, Mapping
from . import institutional_governance as gov
from . import production_governance as pg

VERSION='13.0.9B'
SCHEMA_VERSION='apex.production.canary.v1'
ALLOWED_EXPOSURES=(1,5,10)
TERMINAL={'STOPPED','COMPLETED','ROLLED_BACK','FAILED'}

def _now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def _json(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def _load(v,default=None):
    try:return json.loads(v) if v not in (None,'') else ({} if default is None else default)
    except Exception:return {} if default is None else default

def _conn():
    c=sqlite3.connect(gov.DB_PATH); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c

def init_db():
    pg.init_db()
    with _conn() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS canary_deployments(
          canary_id TEXT PRIMARY KEY,promotion_id TEXT NOT NULL,manifest_id TEXT NOT NULL,domain TEXT NOT NULL,
          champion_version TEXT NOT NULL,challenger_version TEXT NOT NULL,status TEXT NOT NULL,exposure_pct INTEGER NOT NULL,
          strategy_families_json TEXT NOT NULL,regimes_json TEXT NOT NULL,start_time TEXT,end_time TEXT,created_at TEXT NOT NULL,
          created_by TEXT NOT NULL,started_at TEXT,stopped_at TEXT,stop_reason TEXT,health_policy_json TEXT NOT NULL,
          metadata_json TEXT NOT NULL,FOREIGN KEY(promotion_id) REFERENCES production_promotion_requests(promotion_id));
        CREATE UNIQUE INDEX IF NOT EXISTS idx_canary_manifest ON canary_deployments(manifest_id);
        CREATE TABLE IF NOT EXISTS canary_health_events(
          event_id TEXT PRIMARY KEY,canary_id TEXT NOT NULL,observed_at TEXT NOT NULL,event_type TEXT NOT NULL,
          severity TEXT NOT NULL,metrics_json TEXT NOT NULL,action TEXT NOT NULL,reason TEXT NOT NULL,
          FOREIGN KEY(canary_id) REFERENCES canary_deployments(canary_id));
        CREATE TABLE IF NOT EXISTS canary_routing_events(
          routing_id TEXT PRIMARY KEY,canary_id TEXT NOT NULL,recommendation_id TEXT NOT NULL,routed_to TEXT NOT NULL,
          bucket INTEGER NOT NULL,eligible INTEGER NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL,context_json TEXT NOT NULL,
          FOREIGN KEY(canary_id) REFERENCES canary_deployments(canary_id));
        CREATE UNIQUE INDEX IF NOT EXISTS idx_canary_rec ON canary_routing_events(canary_id,recommendation_id);
        CREATE TABLE IF NOT EXISTS canary_rollbacks(
          rollback_id TEXT PRIMARY KEY,canary_id TEXT NOT NULL,from_version TEXT NOT NULL,to_version TEXT NOT NULL,
          created_at TEXT NOT NULL,created_by TEXT NOT NULL,reason TEXT NOT NULL,automatic INTEGER NOT NULL,metadata_json TEXT NOT NULL,
          FOREIGN KEY(canary_id) REFERENCES canary_deployments(canary_id));
        ''')
    return {'ok':True,'schema_version':SCHEMA_VERSION}

def _one(table,key,value):
    init_db()
    with _conn() as c:r=c.execute(f'SELECT * FROM {table} WHERE {key}=?',(value,)).fetchone()
    return dict(r) if r else None

def canary(canary_id):
    d=_one('canary_deployments','canary_id',canary_id)
    if d:
        for k in ('strategy_families_json','regimes_json','health_policy_json','metadata_json'):
            d[k[:-5] if k.endswith('_json') else k]=_load(d.pop(k),[] if k in ('strategy_families_json','regimes_json') else {})
    return d

def _manifest(manifest_id): return _one('production_manifests','manifest_id',manifest_id)

def create(payload:Mapping[str,Any],actor='API'):
    init_db(); manifest_id=str(payload.get('manifest_id') or '').strip(); m=_manifest(manifest_id)
    if not m:return {'ok':False,'status':'UNAVAILABLE','error':'queued production manifest not found'}
    if m['status']!='QUEUED_NOT_DEPLOYED':return {'ok':False,'status':'APPROVAL_REQUIRED','error':'manifest is not queued for canary review'}
    manifest=_load(m['manifest_json']); promotion=pg.promotion(m['promotion_id'])
    exposure=int(payload.get('exposure_pct') or 1)
    if exposure not in ALLOWED_EXPOSURES:return {'ok':False,'status':'UNAVAILABLE','error':'exposure_pct must be 1, 5, or 10'}
    cid=str(uuid.uuid4()); policy={'max_error_rate':float(payload.get('max_error_rate',0.05)),'max_divergence_rate':float(payload.get('max_divergence_rate',0.35)),'max_consecutive_errors':int(payload.get('max_consecutive_errors',3)),'minimum_health_samples':int(payload.get('minimum_health_samples',10))}
    try:
        with _conn() as c:c.execute('INSERT INTO canary_deployments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(cid,m['promotion_id'],manifest_id,promotion['domain'],manifest['current_champion_version'],manifest['proposed_version'],'PENDING_START',exposure,_json(payload.get('strategy_families') or []),_json(payload.get('regimes') or []),payload.get('start_time'),payload.get('end_time'),_now(),actor,None,None,None,_json(policy),_json({'automatic_full_rollout':False,'max_exposure_pct':10,'production_scope':'BOUNDED_CANARY'})))
    except sqlite3.IntegrityError:return {'ok':False,'status':'APPROVAL_REQUIRED','error':'canary already exists for manifest'}
    gov.audit('CREATE_CANARY_DEPLOYMENT','canary_deployment',cid,new={'manifest_id':manifest_id,'exposure_pct':exposure},actor=actor)
    return {'ok':True,'status':'PENDING_START','canary_id':cid,'exposure_pct':exposure,'production_effect':'NONE_UNTIL_STARTED'}

def transition(canary_id,action,actor='API',reason=''):
    d=canary(canary_id)
    if not d:return {'ok':False,'status':'UNAVAILABLE','error':'canary not found'}
    action=str(action).lower(); old=d['status']
    allowed={'start':({'PENDING_START','PAUSED'},'ACTIVE'),'pause':({'ACTIVE'},'PAUSED'),'complete':({'ACTIVE','PAUSED'},'COMPLETED'),'stop':({'PENDING_START','ACTIVE','PAUSED'},'STOPPED')}
    if action not in allowed:return {'ok':False,'status':'UNAVAILABLE','error':'invalid action'}
    states,new=allowed[action]
    if old not in states:return {'ok':False,'status':'APPROVAL_REQUIRED','error':f'cannot {action} from {old}'}
    with _conn() as c:c.execute('UPDATE canary_deployments SET status=?,started_at=COALESCE(started_at,?),stopped_at=?,stop_reason=? WHERE canary_id=?',(new,_now() if new=='ACTIVE' else None,_now() if new in TERMINAL else None,reason if new in TERMINAL or new=='PAUSED' else None,canary_id))
    gov.audit(f'CANARY_{action.upper()}','canary_deployment',canary_id,previous={'status':old},new={'status':new},actor=actor,explanation=reason)
    return {'ok':True,'status':new,'canary_id':canary_id,'production_effect':'BOUNDED_CANARY' if new=='ACTIVE' else 'CHAMPION_ONLY'}

def _eligible(d,context):
    families=d['strategy_families']; regimes=d['regimes']
    if families and str(context.get('strategy_family') or '') not in families:return False,'strategy family outside canary scope'
    if regimes and str(context.get('regime') or '') not in regimes:return False,'regime outside canary scope'
    now=_now()
    if d.get('start_time') and now<d['start_time']:return False,'before canary window'
    if d.get('end_time') and now>d['end_time']:return False,'after canary window'
    return True,'eligible'

def route(canary_id,recommendation_id,context=None,record=True):
    d=canary(canary_id); context=dict(context or {})
    if not d:return {'ok':False,'status':'UNAVAILABLE','error':'canary not found'}
    if d['status']!='ACTIVE':return {'ok':True,'status':d['status'],'routed_to':'CHAMPION','version':d['champion_version'],'reason':'canary not active','production_effect':'CHAMPION_ONLY'}
    eligible,reason=_eligible(d,context); bucket=int(hashlib.sha256(f'{canary_id}:{recommendation_id}'.encode()).hexdigest()[:8],16)%100
    challenger=eligible and bucket<d['exposure_pct']; routed='CHALLENGER' if challenger else 'CHAMPION'; version=d['challenger_version'] if challenger else d['champion_version']
    if record:
        try:
            with _conn() as c:c.execute('INSERT INTO canary_routing_events VALUES(?,?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),canary_id,str(recommendation_id),routed,bucket,1 if eligible else 0,reason,_now(),_json(context)))
        except sqlite3.IntegrityError:pass
    return {'ok':True,'status':'ACTIVE','routed_to':routed,'version':version,'bucket':bucket,'exposure_pct':d['exposure_pct'],'eligible':eligible,'reason':reason,'production_effect':'BOUNDED_CANARY'}

def rollback(canary_id,actor='API',reason='manual rollback',automatic=False):
    d=canary(canary_id)
    if not d:return {'ok':False,'status':'UNAVAILABLE','error':'canary not found'}
    if d['status']=='ROLLED_BACK':return {'ok':False,'status':'APPROVAL_REQUIRED','error':'already rolled back'}
    with _conn() as c:
        c.execute('UPDATE canary_deployments SET status=?,stopped_at=?,stop_reason=? WHERE canary_id=?',('ROLLED_BACK',_now(),reason,canary_id))
        c.execute('INSERT INTO canary_rollbacks VALUES(?,?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),canary_id,d['challenger_version'],d['champion_version'],_now(),actor,reason,1 if automatic else 0,_json({'champion_restored':True})))
    gov.audit('CANARY_ROLLBACK','canary_deployment',canary_id,previous={'status':d['status']},new={'status':'ROLLED_BACK','champion':d['champion_version']},actor=actor,explanation=reason)
    return {'ok':True,'status':'ROLLED_BACK','canary_id':canary_id,'active_version':d['champion_version'],'production_effect':'CHAMPION_ONLY'}

def health(canary_id,payload:Mapping[str,Any],actor='SYSTEM'):
    d=canary(canary_id)
    if not d:return {'ok':False,'status':'UNAVAILABLE','error':'canary not found'}
    metrics=dict(payload.get('metrics') or payload); samples=int(metrics.get('samples',0)); error=float(metrics.get('error_rate',0)); divergence=float(metrics.get('divergence_rate',0)); consecutive=int(metrics.get('consecutive_errors',0)); p=d['health_policy']
    breach=[]
    if samples>=p['minimum_health_samples'] and error>p['max_error_rate']:breach.append('error_rate')
    if samples>=p['minimum_health_samples'] and divergence>p['max_divergence_rate']:breach.append('divergence_rate')
    if consecutive>=p['max_consecutive_errors']:breach.append('consecutive_errors')
    action='ROLLBACK' if breach else 'CONTINUE'; reason='Safety threshold breached: '+','.join(breach) if breach else 'Health within policy'
    with _conn() as c:c.execute('INSERT INTO canary_health_events VALUES(?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),canary_id,_now(),'HEALTH_CHECK','CRITICAL' if breach else 'INFO',_json(metrics),action,reason))
    if breach:return rollback(canary_id,actor=actor,reason=reason,automatic=True) | {'breaches':breach}
    return {'ok':True,'status':d['status'],'action':'CONTINUE','breaches':[],'production_effect':'BOUNDED_CANARY' if d['status']=='ACTIVE' else 'CHAMPION_ONLY'}

def list_canaries(limit=100):
    init_db()
    with _conn() as c:rows=c.execute('SELECT * FROM canary_deployments ORDER BY created_at DESC LIMIT ?',(max(1,min(limit,1000)),)).fetchall()
    return [canary(r['canary_id']) for r in rows]

def events(canary_id=None,limit=100):
    init_db(); sql='SELECT * FROM canary_health_events'; args=[]
    if canary_id:sql+=' WHERE canary_id=?';args.append(canary_id)
    sql+=' ORDER BY observed_at DESC LIMIT ?';args.append(max(1,min(limit,1000)))
    with _conn() as c:rows=c.execute(sql,args).fetchall()
    return [dict(r)|{'metrics':_load(r['metrics_json'])} for r in rows]

def rollbacks(limit=100):
    init_db()
    with _conn() as c:rows=c.execute('SELECT * FROM canary_rollbacks ORDER BY created_at DESC LIMIT ?',(max(1,min(limit,1000)),)).fetchall()
    return [dict(r)|{'metadata':_load(r['metadata_json'])} for r in rows]

def status():
    rows=list_canaries(1000); active=[x for x in rows if x['status']=='ACTIVE']
    return {'schema_version':SCHEMA_VERSION,'status':'ACTIVE' if active else 'READY','canary_count':len(rows),'active_count':len(active),'allowed_exposures':list(ALLOWED_EXPOSURES),'maximum_exposure_pct':10,'automatic_full_rollout':False,'automatic_rollback_enabled':True,'build_version':VERSION}
