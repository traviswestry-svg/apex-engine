"""APEX 16.6 — Live Operations & Data Integrity Command.

Deterministic operational governance for source health, freshness, evidence
completeness, synchronized decision snapshots, session state and tradeability.
May block APEX internal actionability; never mutates recommendations or brokers.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, sqlite3, uuid
from typing import Any
from . import institutional_governance as gov

VERSION='16.6.16.6'; SCHEMA_VERSION='apex.live_operations.v1'
HEALTH_STATES=('HEALTHY','DEGRADED','STALE','DISCONNECTED','ERROR','MARKET_CLOSED','NOT_EXPECTED')
TRADEABILITY_STATES=('TRADEABLE','TRADEABLE_WITH_CAUTION','NOT_TRADEABLE','MARKET_CLOSED')
DEFAULT_THRESHOLDS={'spx_quote':3,'es_quote':3,'options_flow':15,'gamma':60,'auction':30,'volume_profile':30,'market_state':60,'playbook':60,'news':300,'database':30,'scanner':90,'telegram':300}
REQUIRED_RTH=('spx_quote','es_quote','options_flow','gamma','market_state','playbook')
OPTIONAL_RTH=('auction','volume_profile','news','database','scanner','telegram')

def _now_dt(): return dt.datetime.now(dt.timezone.utc)
def _now(): return _now_dt().isoformat()
def _json(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def _conn():
    c=sqlite3.connect(gov.DB_PATH); c.row_factory=sqlite3.Row; return c

def init_db():
    gov.init_db()
    with _conn() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS live_operation_incidents(
          incident_id TEXT PRIMARY KEY, source TEXT NOT NULL, event_type TEXT NOT NULL,
          severity TEXT NOT NULL, status TEXT NOT NULL, observed_at TEXT NOT NULL,
          description TEXT NOT NULL, snapshot_json TEXT NOT NULL, recovery_of TEXT,
          schema_version TEXT NOT NULL, engine_version TEXT NOT NULL,
          integrity_hash TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_loi_time ON live_operation_incidents(observed_at);
        CREATE TABLE IF NOT EXISTS live_operation_assessments(
          assessment_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, observed_at TEXT NOT NULL,
          assessment_json TEXT NOT NULL, schema_version TEXT NOT NULL,
          engine_version TEXT NOT NULL, integrity_hash TEXT NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(symbol,observed_at));
        ''')
    return {'ok':True,'schema_version':SCHEMA_VERSION,'build_version':VERSION}

def _parse(v):
    if isinstance(v,dt.datetime): return v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)
    try:return dt.datetime.fromisoformat(str(v).replace('Z','+00:00'))
    except Exception:return None

def session_state(at:Any=None, holiday=False, early_close=False):
    x=_parse(at) or _now_dt(); x=x.astimezone(dt.timezone(dt.timedelta(hours=-4)))
    if holiday:return 'HOLIDAY'
    if x.weekday()>=5:return 'MARKET_CLOSED'
    m=x.hour*60+x.minute
    if m<240:return 'OVERNIGHT'
    if m<570:return 'PREMARKET'
    if m<585:return 'OPENING_AUCTION'
    if m<630:return 'ACTIVE_RTH'
    if m<690:return 'LATE_MORNING'
    if m<810:return 'MIDDAY'
    close=780 if early_close else 960
    if m<close-60:return 'ACTIVE_RTH'
    if m<close:return 'POWER_HOUR'
    if m<1200:return 'AFTER_HOURS'
    return 'OVERNIGHT'

def _age_seconds(ts, now):
    x=_parse(ts)
    return None if not x else max(0.0,(now-x.astimezone(dt.timezone.utc)).total_seconds())

def evaluate(payload:dict|None=None)->dict[str,Any]:
    p=payload or {}; now=_parse(p.get('observed_at')) or _now_dt(); session=str(p.get('session') or session_state(now,p.get('holiday',False),p.get('early_close',False)))
    thresholds={**DEFAULT_THRESHOLDS,**(p.get('thresholds') or {})}; raw=p.get('sources') or {}
    sources=[]; blocking=[]; warnings=[]
    market_closed=session in ('MARKET_CLOSED','HOLIDAY','AFTER_HOURS','OVERNIGHT')
    required=set(REQUIRED_RTH if not market_closed else ('database',))
    names=sorted(set(thresholds)|set(raw))
    for name in names:
        r=raw.get(name) if isinstance(raw.get(name),dict) else {}
        expected=bool(r.get('expected',name in required or name in OPTIONAL_RTH)) and not (market_closed and name in REQUIRED_RTH)
        max_age=float(r.get('max_age_seconds',thresholds.get(name,60)))
        age=_age_seconds(r.get('last_update') or r.get('timestamp'),now)
        connected=r.get('connected',True); error=r.get('error')
        if not expected: state='NOT_EXPECTED' if not market_closed else 'MARKET_CLOSED'
        elif error: state='ERROR'
        elif connected is False: state='DISCONNECTED'
        elif age is None: state='DISCONNECTED'
        elif age>max_age*2: state='STALE'
        elif age>max_age: state='DEGRADED'
        else: state='HEALTHY'
        item={'source':name,'status':state,'required':name in required,'expected':expected,'age_seconds':None if age is None else round(age,3),'max_age_seconds':max_age,'latency_ms':r.get('latency_ms'),'last_update':r.get('last_update') or r.get('timestamp'),'failure_count':int(r.get('failure_count',0)),'recovery_count':int(r.get('recovery_count',0))}
        sources.append(item)
        if item['required'] and state in ('STALE','DISCONNECTED','ERROR'): blocking.append(f'{name}: {state}')
        elif expected and state=='DEGRADED': warnings.append(f'{name}: DEGRADED')
    available=sum(1 for x in sources if x['expected'] and x['status'] in ('HEALTHY','DEGRADED'))
    expected_count=sum(1 for x in sources if x['expected'])
    completeness=round(100*available/expected_count,2) if expected_count else 100.0
    timestamps=[_parse(x['last_update']) for x in sources if x['required'] and x['last_update'] and x['status'] in ('HEALTHY','DEGRADED')]
    drift=(max(timestamps)-min(timestamps)).total_seconds() if len(timestamps)>1 else 0.0
    max_drift=float(p.get('max_snapshot_drift_seconds',1.0))
    if drift>max_drift:blocking.append(f'decision snapshot drift {round(drift,3)}s exceeds {max_drift}s')
    if market_closed: tradeability='MARKET_CLOSED'
    elif blocking: tradeability='NOT_TRADEABLE'
    elif warnings or completeness<90: tradeability='TRADEABLE_WITH_CAUTION'
    else: tradeability='TRADEABLE'
    if blocking: health='DEGRADED' if tradeability=='NOT_TRADEABLE' else 'HEALTHY'
    elif warnings: health='DEGRADED'
    else: health='HEALTHY'
    newest=max(timestamps).isoformat() if timestamps else None
    oldest=min(timestamps).isoformat() if timestamps else None
    result={'status':'READY','symbol':str(p.get('symbol') or 'SPX'),'observed_at':now.isoformat(),'session':session,'system_health':health,'tradeability':tradeability,'evidence_completeness_score':completeness,'blocking_issues':blocking,'warnings':warnings,'sources':sources,'decision_snapshot':{'valid':not blocking and drift<=max_drift,'drift_seconds':round(drift,3),'max_drift_seconds':max_drift,'newest_timestamp':newest,'oldest_timestamp':oldest},'internal_tradeability_gate_enabled':True,'recommendation_replacement_enabled':False,'broker_order_submission_enabled':False,'production_effect':'NONE'}
    result['integrity_hash']=hashlib.sha256(_json(result).encode()).hexdigest(); return result

def record_assessment(payload:dict,actor='SYSTEM'):
    init_db(); out=evaluate(payload); symbol=out['symbol']; observed=out['observed_at']
    with _conn() as c:r=c.execute('SELECT * FROM live_operation_assessments WHERE symbol=? AND observed_at=?',(symbol,observed)).fetchone()
    if r:return {'ok':True,'status':'IMMUTABLE_EXISTS','created':False,'assessment_id':r['assessment_id'],'assessment':json.loads(r['assessment_json']),'integrity_hash':r['integrity_hash'],'production_effect':'NONE'}
    aid=str(uuid.uuid4()); created=_now()
    with _conn() as c:c.execute('INSERT INTO live_operation_assessments VALUES(?,?,?,?,?,?,?,?)',(aid,symbol,observed,_json(out),SCHEMA_VERSION,VERSION,out['integrity_hash'],created))
    return {'ok':True,'status':'CREATED','created':True,'assessment_id':aid,'assessment':out,'integrity_hash':out['integrity_hash'],'created_at':created,'production_effect':'NONE'}

def record_incident(source,event_type,severity,description,snapshot=None,recovery_of=None,actor='SYSTEM'):
    init_db(); observed=_now(); payload={'source':source,'event_type':event_type,'severity':severity,'description':description,'snapshot':snapshot or {},'recovery_of':recovery_of,'observed_at':observed}; ih=hashlib.sha256(_json(payload).encode()).hexdigest(); iid=str(uuid.uuid4())
    with _conn() as c:c.execute('INSERT INTO live_operation_incidents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(iid,source,event_type,severity,'RECOVERED' if recovery_of else 'OPEN',observed,description,_json(snapshot or {}),recovery_of,SCHEMA_VERSION,VERSION,ih,_now()))
    return {'ok':True,'created':True,'incident_id':iid,**payload,'integrity_hash':ih,'production_effect':'NONE'}

def incidents(limit=100):
    init_db()
    with _conn() as c:rows=c.execute('SELECT * FROM live_operation_incidents ORDER BY observed_at DESC LIMIT ?',(max(1,min(int(limit),1000)),)).fetchall()
    out=[]
    for r in rows:
        d=dict(r); d['snapshot']=json.loads(d.pop('snapshot_json')); out.append(d)
    return out

def latest(symbol='SPX'):
    init_db()
    with _conn() as c:r=c.execute('SELECT * FROM live_operation_assessments WHERE symbol=? ORDER BY observed_at DESC LIMIT 1',(symbol,)).fetchone()
    return json.loads(r['assessment_json']) if r else evaluate({'symbol':symbol,'session':'MARKET_CLOSED','sources':{'database':{'last_update':_now()}}})

def status():
    init_db()
    with _conn() as c:i=c.execute('SELECT COUNT(*) n FROM live_operation_incidents').fetchone()['n'];a=c.execute('SELECT COUNT(*) n FROM live_operation_assessments').fetchone()['n']
    return {'status':'READY','engine':'LIVE_OPERATIONS','build_version':VERSION,'schema_version':SCHEMA_VERSION,'incident_count':i,'assessment_count':a,'health_states':HEALTH_STATES,'tradeability_states':TRADEABILITY_STATES,'internal_tradeability_gate_enabled':True,'broker_order_submission_enabled':False,'live_order_mutation_enabled':False,'recommendation_replacement_enabled':False,'production_effect':'NONE'}

def dashboard(symbol='SPX'):return {'ok':True,'status':'READY','assessment':latest(symbol),'incidents':incidents(50),'safety':status()}
