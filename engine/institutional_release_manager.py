"""APEX 13 Sprint 9C: institutional release manager.

Consolidates approved promotion manifests, canary operations, health, audit, and
rollback history into immutable release records. It never replaces the champion
or changes trading logic.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, sqlite3, uuid
from typing import Any, Mapping
from . import institutional_governance as gov
from . import production_governance as pg
from . import canary_deployment as cd

VERSION='13.0.9C'
SCHEMA_VERSION='apex.production.release.v1'

def _now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def _json(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def _load(v,d=None):
    try:return json.loads(v) if v not in (None,'') else ({} if d is None else d)
    except Exception:return {} if d is None else d

def _conn():
    c=sqlite3.connect(gov.DB_PATH); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c

def init_db():
    pg.init_db(); cd.init_db()
    with _conn() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS institutional_releases(
          release_id TEXT PRIMARY KEY,release_name TEXT NOT NULL,domain TEXT NOT NULL,promotion_id TEXT NOT NULL,
          manifest_id TEXT NOT NULL,canary_id TEXT,champion_version TEXT NOT NULL,challenger_version TEXT NOT NULL,
          status TEXT NOT NULL,created_at TEXT NOT NULL,created_by TEXT NOT NULL,closed_at TEXT,closed_by TEXT,
          release_notes TEXT NOT NULL,operational_summary_json TEXT NOT NULL,limitations_json TEXT NOT NULL,
          integrity_hash TEXT NOT NULL,metadata_json TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_release_manifest ON institutional_releases(manifest_id);
        CREATE TABLE IF NOT EXISTS release_timeline_events(
          event_id TEXT PRIMARY KEY,release_id TEXT NOT NULL,event_time TEXT NOT NULL,event_type TEXT NOT NULL,
          actor TEXT NOT NULL,detail_json TEXT NOT NULL,integrity_hash TEXT NOT NULL,
          FOREIGN KEY(release_id) REFERENCES institutional_releases(release_id));
        CREATE TABLE IF NOT EXISTS release_health_snapshots(
          snapshot_id TEXT PRIMARY KEY,release_id TEXT NOT NULL,captured_at TEXT NOT NULL,status TEXT NOT NULL,
          metrics_json TEXT NOT NULL,source_json TEXT NOT NULL,integrity_hash TEXT NOT NULL,
          FOREIGN KEY(release_id) REFERENCES institutional_releases(release_id));
        ''')
    return {'ok':True,'schema_version':SCHEMA_VERSION}

def _one(table,key,value):
    init_db()
    with _conn() as c:r=c.execute(f'SELECT * FROM {table} WHERE {key}=?',(value,)).fetchone()
    return dict(r) if r else None

def release(release_id):
    d=_one('institutional_releases','release_id',release_id)
    if not d:return None
    d['operational_summary']=_load(d.pop('operational_summary_json'))
    d['limitations']=_load(d.pop('limitations_json'),[])
    d['metadata']=_load(d.pop('metadata_json'))
    d['timeline']=timeline(release_id,200)
    return d

def _manifest(mid): return _one('production_manifests','manifest_id',mid)
def _canary(cid): return cd.canary(cid) if cid else None

def _event(release_id,event_type,actor,detail):
    raw=_json({'release_id':release_id,'event_type':event_type,'actor':actor,'detail':detail,'event_time':_now()})
    h=hashlib.sha256(raw.encode()).hexdigest()
    with _conn() as c:c.execute('INSERT INTO release_timeline_events VALUES(?,?,?,?,?,?,?)',(str(uuid.uuid4()),release_id,_now(),event_type,actor,_json(detail),h))

def create(payload:Mapping[str,Any],actor='API'):
    init_db(); mid=str(payload.get('manifest_id') or ''); m=_manifest(mid)
    if not m:return {'ok':False,'status':'UNAVAILABLE','error':'production manifest not found'}
    if m['status']!='QUEUED_NOT_DEPLOYED':return {'ok':False,'status':'APPROVAL_REQUIRED','error':'manifest is not release-manager eligible'}
    manifest=_load(m['manifest_json']); cid=str(payload.get('canary_id') or '') or None; can=_canary(cid)
    if cid and not can:return {'ok':False,'status':'UNAVAILABLE','error':'canary not found'}
    if can and can['manifest_id']!=mid:return {'ok':False,'status':'APPROVAL_REQUIRED','error':'canary does not belong to manifest'}
    rid=str(uuid.uuid4()); name=str(payload.get('release_name') or f"APEX release {manifest.get('proposed_version','candidate')}")
    summary={'promotion_status':'QUEUED_NOT_DEPLOYED','canary_status':can['status'] if can else 'NOT_CREATED','health_state':'NOT_EVALUATED','production_effect':'NONE' if not can or can['status']!='ACTIVE' else 'BOUNDED_CANARY'}
    limitations=['No automatic champion replacement','No automatic exposure increase','Release close is administrative and does not deploy code']
    base={'release_id':rid,'manifest_id':mid,'canary_id':cid,'champion':manifest.get('current_champion_version'),'challenger':manifest.get('proposed_version'),'created_at':_now(),'summary':summary}
    h=hashlib.sha256(_json(base).encode()).hexdigest()
    try:
        with _conn() as c:c.execute('INSERT INTO institutional_releases VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(rid,name,str(manifest.get('domain') or 'decision_weights'),m['promotion_id'],mid,cid,str(manifest.get('current_champion_version')),str(manifest.get('proposed_version')),'OPEN',_now(),actor,None,None,str(payload.get('release_notes') or manifest.get('release_notes') or ''),_json(summary),_json(limitations),h,_json({'automatic_champion_replacement':False,'immutable_identity':True})))
    except sqlite3.IntegrityError:return {'ok':False,'status':'APPROVAL_REQUIRED','error':'release already exists for manifest'}
    _event(rid,'RELEASE_OPENED',actor,base); gov.audit('OPEN_INSTITUTIONAL_RELEASE','institutional_release',rid,new=base,actor=actor)
    return {'ok':True,'status':'OPEN','release_id':rid,'integrity_hash':h,'production_effect':summary['production_effect']}

def capture_health(release_id,actor='SYSTEM'):
    r=release(release_id)
    if not r:return {'ok':False,'status':'UNAVAILABLE','error':'release not found'}
    can=_canary(r.get('canary_id')); events=cd.events(r.get('canary_id'),1000) if can else []; routes=[]
    if can:
        with _conn() as c: routes=[dict(x) for x in c.execute('SELECT * FROM canary_routing_events WHERE canary_id=?',(can['canary_id'],)).fetchall()]
    challenger=sum(1 for x in routes if x['routed_to']=='CHALLENGER'); total=len(routes)
    metrics={'canary_status':can['status'] if can else 'NOT_CREATED','routing_samples':total,'challenger_routes':challenger,'challenger_share':round(challenger/total,4) if total else 0.0,'health_events':len(events),'critical_events':sum(1 for x in events if x.get('severity')=='CRITICAL'),'rollback_count':sum(1 for x in cd.rollbacks(1000) if x.get('canary_id')==r.get('canary_id'))}
    status='ROLLED_BACK' if can and can['status']=='ROLLED_BACK' else ('HEALTHY' if can and can['status'] in {'ACTIVE','COMPLETED'} and not metrics['critical_events'] else 'OBSERVING')
    raw=_json({'release_id':release_id,'captured_at':_now(),'status':status,'metrics':metrics}); h=hashlib.sha256(raw.encode()).hexdigest()
    with _conn() as c:c.execute('INSERT INTO release_health_snapshots VALUES(?,?,?,?,?,?,?)',(str(uuid.uuid4()),release_id,_now(),status,_json(metrics),_json({'canary_id':r.get('canary_id'),'real_events_only':True}),h))
    _event(release_id,'HEALTH_SNAPSHOT',actor,{'status':status,'metrics':metrics})
    return {'ok':True,'status':status,'release_id':release_id,'metrics':metrics,'integrity_hash':h,'production_effect':'CHAMPION_ONLY' if status=='ROLLED_BACK' else r['operational_summary'].get('production_effect')}

def close(release_id,actor='API',disposition='CLOSED',note=''):
    r=release(release_id)
    if not r:return {'ok':False,'status':'UNAVAILABLE','error':'release not found'}
    if r['status']!='OPEN':return {'ok':False,'status':'APPROVAL_REQUIRED','error':'release is not open'}
    disposition=str(disposition).upper()
    if disposition not in {'CLOSED','ROLLED_BACK','REJECTED'}:return {'ok':False,'status':'UNAVAILABLE','error':'invalid disposition'}
    can=_canary(r.get('canary_id'))
    if disposition=='CLOSED' and can and can['status'] not in {'COMPLETED','STOPPED','ROLLED_BACK'}:
        return {'ok':False,'status':'APPROVAL_REQUIRED','error':'canary must be completed, stopped, or rolled back before release close'}
    with _conn() as c:c.execute('UPDATE institutional_releases SET status=?,closed_at=?,closed_by=? WHERE release_id=?',(disposition,_now(),actor,release_id))
    _event(release_id,'RELEASE_CLOSED',actor,{'disposition':disposition,'note':note,'champion_replaced':False})
    gov.audit('CLOSE_INSTITUTIONAL_RELEASE','institutional_release',release_id,previous={'status':'OPEN'},new={'status':disposition,'champion_replaced':False},actor=actor,explanation=note)
    return {'ok':True,'status':disposition,'release_id':release_id,'champion_replaced':False,'production_effect':'CHAMPION_ONLY' if disposition=='ROLLED_BACK' else 'NO_AUTOMATIC_CHANGE'}

def list_releases(limit=100):
    init_db()
    with _conn() as c:rows=c.execute('SELECT * FROM institutional_releases ORDER BY created_at DESC LIMIT ?',(max(1,min(limit,1000)),)).fetchall()
    out=[]
    for x in rows:
        d=dict(x); d['operational_summary']=_load(d.pop('operational_summary_json')); d['limitations']=_load(d.pop('limitations_json'),[]); d['metadata']=_load(d.pop('metadata_json')); out.append(d)
    return out

def timeline(release_id,limit=100):
    init_db()
    with _conn() as c:rows=c.execute('SELECT * FROM release_timeline_events WHERE release_id=? ORDER BY event_time DESC LIMIT ?',(release_id,max(1,min(limit,1000)))).fetchall()
    return [dict(x)|{'detail':_load(x['detail_json'])} for x in rows]

def health_snapshots(release_id=None,limit=100):
    init_db(); q='SELECT * FROM release_health_snapshots'; a=[]
    if release_id:q+=' WHERE release_id=?';a.append(release_id)
    q+=' ORDER BY captured_at DESC LIMIT ?';a.append(max(1,min(limit,1000)))
    with _conn() as c:rows=c.execute(q,a).fetchall()
    return [dict(x)|{'metrics':_load(x['metrics_json']),'source':_load(x['source_json'])} for x in rows]

def status():
    rs=list_releases(1000)
    return {'schema_version':SCHEMA_VERSION,'status':'READY','release_count':len(rs),'open_count':sum(1 for r in rs if r['status']=='OPEN'),'closed_count':sum(1 for r in rs if r['status']!='OPEN'),'automatic_champion_replacement':False,'automatic_rollout':False,'production_mutation_enabled':False,'build_version':VERSION}
