"""APEX 15.5: Institutional Research Lab and Alpha Attribution.

Governed, offline experiment registry and immutable alpha attribution. No
candidate can affect production without the existing promotion pipeline.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, sqlite3, uuid
from typing import Any
from . import institutional_governance as gov

VERSION='15.0.15.5'; SCHEMA_VERSION='apex.irl.v1'
ALLOWED_TYPES={'INDICATOR','FILTER','PLAYBOOK','CONFIDENCE_MODEL','EXECUTION_POLICY','STRATEGY','DATA_FEATURE'}
ALLOWED_STAGES={'DRAFT','OFFLINE_TEST','SHADOW','CHALLENGER','APPROVED','REJECTED','ARCHIVED'}


def _now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def _json(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def _load(v,d=None):
    try:return json.loads(v)
    except Exception:return {} if d is None else d
def _conn():
    c=sqlite3.connect(gov.DB_PATH); c.row_factory=sqlite3.Row; return c

def init_db():
    gov.init_db()
    with _conn() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS research_candidates(
          candidate_id TEXT PRIMARY KEY, name TEXT NOT NULL, candidate_type TEXT NOT NULL,
          hypothesis TEXT NOT NULL, specification_json TEXT NOT NULL, stage TEXT NOT NULL,
          owner TEXT NOT NULL, schema_version TEXT NOT NULL, engine_version TEXT NOT NULL,
          integrity_hash TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(name,candidate_type));
        CREATE TABLE IF NOT EXISTS research_runs(
          run_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, dataset_id TEXT NOT NULL,
          started_at TEXT NOT NULL, completed_at TEXT NOT NULL, methodology_json TEXT NOT NULL,
          metrics_json TEXT NOT NULL, diagnostics_json TEXT NOT NULL, schema_version TEXT NOT NULL,
          engine_version TEXT NOT NULL, integrity_hash TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_research_runs_candidate ON research_runs(candidate_id,completed_at);
        CREATE TABLE IF NOT EXISTS alpha_attribution_records(
          attribution_id TEXT PRIMARY KEY, scope_id TEXT NOT NULL UNIQUE, observed_at TEXT NOT NULL,
          total_result REAL NOT NULL, contributions_json TEXT NOT NULL, normalized_json TEXT NOT NULL,
          diagnostics_json TEXT NOT NULL, schema_version TEXT NOT NULL, engine_version TEXT NOT NULL,
          integrity_hash TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS promotion_readiness_assessments(
          assessment_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, assessed_at TEXT NOT NULL,
          gates_json TEXT NOT NULL, summary_json TEXT NOT NULL, schema_version TEXT NOT NULL,
          engine_version TEXT NOT NULL, integrity_hash TEXT NOT NULL, created_at TEXT NOT NULL);
        ''')
    return {'ok':True,'status':'READY','schema_version':SCHEMA_VERSION,'build_version':VERSION}

def register_candidate(*,name:str,candidate_type:str,hypothesis:str,specification:dict|None=None,owner='SYSTEM',actor='SYSTEM'):
    init_db(); ct=str(candidate_type).upper()
    if ct not in ALLOWED_TYPES:return {'ok':False,'status':'INVALID_CANDIDATE_TYPE','allowed':sorted(ALLOWED_TYPES)}
    with _conn() as c:r=c.execute('SELECT * FROM research_candidates WHERE name=? AND candidate_type=?',(name,ct)).fetchone()
    if r:return {'ok':True,'status':'IMMUTABLE_EXISTS','created':False,**_decode_candidate(dict(r)),'production_effect':'NONE'}
    cid=str(uuid.uuid4()); created=_now(); payload={'name':name,'candidate_type':ct,'hypothesis':hypothesis,'specification':specification or {},'stage':'DRAFT','owner':owner}
    ih=hashlib.sha256(_json(payload).encode()).hexdigest()
    with _conn() as c:c.execute('INSERT INTO research_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?)',(cid,name,ct,hypothesis,_json(specification or {}),'DRAFT',owner,SCHEMA_VERSION,VERSION,ih,created))
    gov.audit('REGISTER_RESEARCH_CANDIDATE','research_candidate',cid,new={'name':name,'type':ct,'integrity_hash':ih},actor=actor,explanation='Immutable offline research candidate registration')
    return {'ok':True,'status':'CREATED','created':True,'candidate_id':cid,**payload,'integrity_hash':ih,'created_at':created,'production_effect':'NONE'}

def _decode_candidate(d): d['specification']=_load(d.pop('specification_json')); return d

def candidates(limit=100):
    init_db()
    with _conn() as c:return [_decode_candidate(dict(r)) for r in c.execute('SELECT * FROM research_candidates ORDER BY created_at DESC LIMIT ?',(max(1,min(int(limit),1000)),)).fetchall()]

def record_run(*,candidate_id:str,dataset_id:str,started_at:str,completed_at:str,methodology:dict,metrics:dict,diagnostics:dict|None=None,actor='SYSTEM'):
    init_db()
    with _conn() as c:candidate=c.execute('SELECT candidate_id FROM research_candidates WHERE candidate_id=?',(candidate_id,)).fetchone()
    if not candidate:return {'ok':False,'status':'CANDIDATE_NOT_FOUND'}
    payload={'candidate_id':candidate_id,'dataset_id':dataset_id,'started_at':started_at,'completed_at':completed_at,'methodology':methodology,'metrics':metrics,'diagnostics':diagnostics or {}}
    ih=hashlib.sha256(_json(payload).encode()).hexdigest()
    with _conn() as c:r=c.execute('SELECT * FROM research_runs WHERE integrity_hash=?',(ih,)).fetchone()
    if r:return {'ok':True,'status':'IMMUTABLE_EXISTS','created':False,**_decode_run(dict(r)),'production_effect':'NONE'}
    rid=str(uuid.uuid4()); created=_now()
    with _conn() as c:c.execute('INSERT INTO research_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(rid,candidate_id,dataset_id,started_at,completed_at,_json(methodology),_json(metrics),_json(diagnostics or {}),SCHEMA_VERSION,VERSION,ih,created))
    gov.audit('CREATE_RESEARCH_RUN','research_run',rid,new={'candidate_id':candidate_id,'integrity_hash':ih},actor=actor,explanation='Immutable offline research result')
    return {'ok':True,'status':'CREATED','created':True,'run_id':rid,**payload,'integrity_hash':ih,'created_at':created,'production_effect':'NONE'}

def _decode_run(d):
    d['methodology']=_load(d.pop('methodology_json')); d['metrics']=_load(d.pop('metrics_json')); d['diagnostics']=_load(d.pop('diagnostics_json')); return d

def runs(candidate_id=None,limit=100):
    init_db(); q='SELECT * FROM research_runs WHERE 1=1'; a=[]
    if candidate_id:q+=' AND candidate_id=?';a.append(candidate_id)
    q+=' ORDER BY completed_at DESC LIMIT ?';a.append(max(1,min(int(limit),1000)))
    with _conn() as c:return [_decode_run(dict(r)) for r in c.execute(q,a).fetchall()]

def compare(candidate_ids:list[str]):
    out=[]
    for cid in candidate_ids:
        rs=runs(cid,1000); n=len(rs)
        def avg(k): return round(sum(float(x['metrics'].get(k) or 0) for x in rs)/n,4) if n else 0.0
        out.append({'candidate_id':cid,'sample_runs':n,'average_expectancy':avg('expectancy'),'average_win_rate':avg('win_rate'),'average_sharpe':avg('sharpe'),'average_max_drawdown':avg('max_drawdown')})
    out.sort(key=lambda x:(x['average_expectancy'],x['average_sharpe']),reverse=True)
    return {'ok':True,'status':'READY','comparison':out,'winner_candidate_id':out[0]['candidate_id'] if out else None,'production_effect':'NONE'}

def alpha_attribution(*,scope_id:str,total_result:float,contributions:dict[str,float],observed_at:str|None=None,actor='SYSTEM'):
    init_db(); observed_at=observed_at or _now(); vals={str(k):round(float(v),6) for k,v in contributions.items()}; denom=sum(abs(v) for v in vals.values())
    normalized={k:round((abs(v)/denom*100) if denom else 0.0,2) for k,v in sorted(vals.items())}
    diagnostics={'reconciles_to_total':round(sum(vals.values()),6)==round(float(total_result),6),'unattributed_result':round(float(total_result)-sum(vals.values()),6),'causal_claim':False,'descriptive_only':True,'production_effect':'NONE'}
    payload={'scope_id':scope_id,'observed_at':observed_at,'total_result':float(total_result),'contributions':vals,'normalized':normalized,'diagnostics':diagnostics}
    ih=hashlib.sha256(_json(payload).encode()).hexdigest()
    with _conn() as c:r=c.execute('SELECT * FROM alpha_attribution_records WHERE scope_id=?',(scope_id,)).fetchone()
    if r:return {'ok':True,'status':'IMMUTABLE_EXISTS','created':False,**_decode_attr(dict(r)),'production_effect':'NONE'}
    aid=str(uuid.uuid4()); created=_now()
    with _conn() as c:c.execute('INSERT INTO alpha_attribution_records VALUES(?,?,?,?,?,?,?,?,?,?,?)',(aid,scope_id,observed_at,float(total_result),_json(vals),_json(normalized),_json(diagnostics),SCHEMA_VERSION,VERSION,ih,created))
    gov.audit('CREATE_ALPHA_ATTRIBUTION','alpha_attribution',aid,new={'scope_id':scope_id,'integrity_hash':ih},actor=actor,explanation='Immutable descriptive subsystem attribution')
    return {'ok':True,'status':'CREATED','created':True,'attribution_id':aid,**payload,'integrity_hash':ih,'created_at':created,'production_effect':'NONE'}

def _decode_attr(d):
    d['contributions']=_load(d.pop('contributions_json')); d['normalized']=_load(d.pop('normalized_json')); d['diagnostics']=_load(d.pop('diagnostics_json')); return d

def attributions(limit=100):
    init_db()
    with _conn() as c:return [_decode_attr(dict(r)) for r in c.execute('SELECT * FROM alpha_attribution_records ORDER BY observed_at DESC LIMIT ?',(max(1,min(int(limit),1000)),)).fetchall()]

def assess_readiness(candidate_id:str,persist=False,actor='SYSTEM'):
    rs=runs(candidate_id,1000); n=len(rs)
    latest=rs[0]['metrics'] if rs else {}
    gates={'minimum_runs':{'pass':n>=3,'value':n,'required':3},'positive_expectancy':{'pass':float(latest.get('expectancy') or 0)>0,'value':latest.get('expectancy')},'drawdown_limit':{'pass':abs(float(latest.get('max_drawdown') or 999))<=20,'value':latest.get('max_drawdown'),'required_max_abs':20},'lookahead_free':{'pass':all(not bool(r['diagnostics'].get('lookahead_detected')) for r in rs),'value':True},'reproducible':{'pass':all(bool(r['diagnostics'].get('reproducible',True)) for r in rs),'value':True}}
    passed=all(x['pass'] for x in gates.values()); summary={'ready_for_governance_review':passed,'approved_for_production':False,'automatic_promotion':False,'required_next_stage':'SHADOW' if passed else 'OFFLINE_TEST','production_effect':'NONE'}
    out={'ok':True,'status':'READY','candidate_id':candidate_id,'gates':gates,'summary':summary}
    if persist:
        aid=str(uuid.uuid4()); created=_now(); ih=hashlib.sha256(_json(out).encode()).hexdigest()
        with _conn() as c:c.execute('INSERT INTO promotion_readiness_assessments VALUES(?,?,?,?,?,?,?,?,?)',(aid,candidate_id,created,_json(gates),_json(summary),SCHEMA_VERSION,VERSION,ih,created))
        out.update({'assessment_id':aid,'integrity_hash':ih,'created':True,'created_at':created})
    return out

def dashboard(): return {'ok':True,'status':'READY','candidates':candidates(50),'recent_runs':runs(None,50),'attributions':attributions(50),'safety':status()}
def status():
    init_db()
    with _conn() as c:
        counts={t:c.execute(f'SELECT COUNT(*) n FROM {t}').fetchone()['n'] for t in ('research_candidates','research_runs','alpha_attribution_records','promotion_readiness_assessments')}
    return {'status':'READY','schema_version':SCHEMA_VERSION,'build_version':VERSION,**counts,'offline_research_only':True,'production_candidate_activation_enabled':False,'automatic_promotion_enabled':False,'live_decision_feedback_enabled':False,'broker_effect':'NONE','production_effect':'NONE'}
