"""APEX 16.7 — Governed Strategy Promotion & Champion/Challenger Control.

Deterministic, evidence-only promotion governance. Produces review states and
immutable decisions; never changes production strategy, weights, confidence,
risk policy, recommendations, or broker state automatically.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, sqlite3, uuid
from typing import Any
from . import institutional_governance as gov

VERSION='16.7.16.7'; SCHEMA_VERSION='apex.strategy_promotion.v1'
PROMOTION_STATES=('REJECTED','MORE_DATA_REQUIRED','SHADOW_MODE','CHALLENGER_APPROVED','LIMITED_RELEASE','PRODUCTION_CANDIDATE')
APPROVAL_STATES=('PENDING_REVIEW','APPROVED','REJECTED','REVOKED')
DEFAULT_POLICY={
 'minimum_sample':30,'minimum_shadow_sample':20,'minimum_win_rate':55.0,
 'minimum_average_r':0.20,'minimum_profit_factor':1.20,'maximum_drawdown_r':6.0,
 'minimum_calibration_score':65.0,'minimum_execution_quality':70.0,
 'minimum_data_integrity':90.0,'minimum_regime_coverage':3,
 'limited_release_max_allocation_pct':10.0,
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
  CREATE TABLE IF NOT EXISTS strategy_promotion_candidates(
    candidate_id TEXT PRIMARY KEY, strategy_id TEXT NOT NULL, version TEXT NOT NULL,
    champion_id TEXT, submitted_at TEXT NOT NULL, candidate_json TEXT NOT NULL,
    schema_version TEXT NOT NULL, engine_version TEXT NOT NULL,
    integrity_hash TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(strategy_id,version));
  CREATE TABLE IF NOT EXISTS strategy_promotion_decisions(
    decision_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, observed_at TEXT NOT NULL,
    state TEXT NOT NULL, approval_state TEXT NOT NULL, decision_json TEXT NOT NULL,
    reviewer TEXT, rationale TEXT, schema_version TEXT NOT NULL,
    engine_version TEXT NOT NULL, integrity_hash TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(candidate_id,observed_at));
  CREATE INDEX IF NOT EXISTS idx_spd_candidate_time ON strategy_promotion_decisions(candidate_id,observed_at);
  CREATE TABLE IF NOT EXISTS strategy_promotion_approvals(
    approval_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL, action TEXT NOT NULL,
    reviewer TEXT NOT NULL, rationale TEXT NOT NULL, observed_at TEXT NOT NULL,
    approval_json TEXT NOT NULL, schema_version TEXT NOT NULL,
    engine_version TEXT NOT NULL, integrity_hash TEXT NOT NULL, created_at TEXT NOT NULL);
  ''')
 return {'ok':True,'schema_version':SCHEMA_VERSION,'build_version':VERSION}

def _num(v,default=0.0):
 try:return float(v)
 except Exception:return default

def _metric(p,*keys,default=0.0):
 for key in keys:
  cur=p
  ok=True
  for part in key.split('.'):
   if isinstance(cur,dict) and part in cur: cur=cur[part]
   else: ok=False; break
  if ok and cur is not None:return _num(cur,default)
 return default

def evaluate(payload:dict|None=None)->dict[str,Any]:
 p=payload or {}; policy={**DEFAULT_POLICY,**(p.get('policy') or {})}
 candidate=p.get('candidate') if isinstance(p.get('candidate'),dict) else p
 metrics=candidate.get('metrics') if isinstance(candidate.get('metrics'),dict) else candidate
 sample=int(_metric(metrics,'sample_size','trades'))
 shadow=int(_metric(metrics,'shadow_sample_size','shadow_trades'))
 win=_metric(metrics,'win_rate')
 avg_r=_metric(metrics,'average_r','avg_r')
 pf=_metric(metrics,'profit_factor')
 dd=abs(_metric(metrics,'max_drawdown_r','drawdown_r'))
 calibration=_metric(metrics,'calibration_score')
 execution=_metric(metrics,'execution_quality_score','execution_quality')
 integrity=_metric(metrics,'data_integrity_score','evidence_completeness_score')
 regimes=int(_metric(metrics,'regime_coverage_count','regime_count'))
 severe=bool(candidate.get('safety_breach') or candidate.get('lookahead_bias') or candidate.get('data_leakage') or candidate.get('broker_mutation'))
 blockers=[]; warnings=[]; passed=[]
 checks=[
  ('sample_size',sample>=int(policy['minimum_sample']),sample,policy['minimum_sample']),
  ('win_rate',win>=policy['minimum_win_rate'],win,policy['minimum_win_rate']),
  ('average_r',avg_r>=policy['minimum_average_r'],avg_r,policy['minimum_average_r']),
  ('profit_factor',pf>=policy['minimum_profit_factor'],pf,policy['minimum_profit_factor']),
  ('max_drawdown_r',dd<=policy['maximum_drawdown_r'],dd,policy['maximum_drawdown_r']),
  ('calibration_score',calibration>=policy['minimum_calibration_score'],calibration,policy['minimum_calibration_score']),
  ('execution_quality',execution>=policy['minimum_execution_quality'],execution,policy['minimum_execution_quality']),
  ('data_integrity',integrity>=policy['minimum_data_integrity'],integrity,policy['minimum_data_integrity']),
  ('regime_coverage',regimes>=int(policy['minimum_regime_coverage']),regimes,policy['minimum_regime_coverage']),
 ]
 for name,ok,value,threshold in checks:
  (passed if ok else blockers).append({'gate':name,'value':value,'threshold':threshold,'passed':ok})
 champion=p.get('champion') if isinstance(p.get('champion'),dict) else {}
 comparison={}
 if champion:
  comparison={'average_r_delta':round(avg_r-_metric(champion,'average_r','avg_r'),3),'profit_factor_delta':round(pf-_metric(champion,'profit_factor'),3),'win_rate_delta':round(win-_metric(champion,'win_rate'),3),'drawdown_improvement_r':round(abs(_metric(champion,'max_drawdown_r','drawdown_r'))-dd,3)}
  if comparison['average_r_delta']<=0 and comparison['profit_factor_delta']<=0:warnings.append('challenger has not demonstrated expectancy improvement over champion')
 approved_shadow=bool(candidate.get('shadow_mode_complete') or shadow>=int(policy['minimum_shadow_sample']))
 explicit_limited=bool(candidate.get('limited_release_complete'))
 if severe: state='REJECTED'; blockers.append({'gate':'safety_integrity','value':'FAILED','threshold':'PASS','passed':False})
 elif sample<int(policy['minimum_sample']): state='MORE_DATA_REQUIRED'
 elif any(x['gate'] in ('data_integrity','max_drawdown_r') for x in blockers): state='REJECTED'
 elif blockers: state='SHADOW_MODE'
 elif not approved_shadow: state='SHADOW_MODE'
 elif champion and warnings: state='CHALLENGER_APPROVED'
 elif not explicit_limited: state='LIMITED_RELEASE'
 else: state='PRODUCTION_CANDIDATE'
 score=round(100*len(passed)/len(checks),2)
 result={'status':'READY','strategy_id':str(candidate.get('strategy_id') or p.get('strategy_id') or 'UNSPECIFIED'),'version':str(candidate.get('version') or p.get('version') or 'UNVERSIONED'),'promotion_state':state,'governance_score':score,'approval_required':state in ('CHALLENGER_APPROVED','LIMITED_RELEASE','PRODUCTION_CANDIDATE'),'automatic_promotion_enabled':False,'gates_passed':passed,'gates_failed':blockers,'warnings':warnings,'champion_comparison':comparison,'policy':policy,'recommended_allocation_pct':policy['limited_release_max_allocation_pct'] if state=='LIMITED_RELEASE' else 0.0,'production_effect':'NONE','recommendation_mutation_enabled':False,'confidence_mutation_enabled':False,'broker_order_submission_enabled':False}
 result['integrity_hash']=_hash(result); return result

def submit_candidate(payload:dict,actor='API'):
 init_db(); cnd=payload.get('candidate') if isinstance(payload.get('candidate'),dict) else payload
 sid=str(cnd.get('strategy_id') or 'UNSPECIFIED'); ver=str(cnd.get('version') or 'UNVERSIONED')
 with _conn() as c:r=c.execute('SELECT * FROM strategy_promotion_candidates WHERE strategy_id=? AND version=?',(sid,ver)).fetchone()
 if r:return {'ok':True,'status':'IMMUTABLE_EXISTS','created':False,'candidate_id':r['candidate_id'],'candidate':json.loads(r['candidate_json']),'integrity_hash':r['integrity_hash'],'production_effect':'NONE'}
 cid=str(uuid.uuid4()); now=_now(); body={'candidate':cnd,'submitted_by':actor,'submitted_at':now}; ih=_hash(body)
 with _conn() as c:c.execute('INSERT INTO strategy_promotion_candidates VALUES(?,?,?,?,?,?,?,?,?,?)',(cid,sid,ver,cnd.get('champion_id'),now,_json(body),SCHEMA_VERSION,VERSION,ih,now))
 return {'ok':True,'status':'CREATED','created':True,'candidate_id':cid,'candidate':body,'integrity_hash':ih,'production_effect':'NONE'}

def record_decision(payload:dict,actor='SYSTEM'):
 init_db(); candidate_id=str(payload.get('candidate_id') or '')
 if not candidate_id:return {'ok':False,'status':'INVALID','error':'candidate_id_required','production_effect':'NONE'}
 observed=str(payload.get('observed_at') or _now())
 with _conn() as c:r=c.execute('SELECT * FROM strategy_promotion_decisions WHERE candidate_id=? AND observed_at=?',(candidate_id,observed)).fetchone()
 if r:return {'ok':True,'status':'IMMUTABLE_EXISTS','created':False,'decision_id':r['decision_id'],'decision':json.loads(r['decision_json']),'integrity_hash':r['integrity_hash'],'production_effect':'NONE'}
 out=evaluate(payload); did=str(uuid.uuid4()); body={**out,'candidate_id':candidate_id,'observed_at':observed,'recorded_by':actor}; ih=_hash(body)
 with _conn() as c:c.execute('INSERT INTO strategy_promotion_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(did,candidate_id,observed,out['promotion_state'],'PENDING_REVIEW',_json(body),None,None,SCHEMA_VERSION,VERSION,ih,_now()))
 return {'ok':True,'status':'CREATED','created':True,'decision_id':did,'decision':body,'integrity_hash':ih,'production_effect':'NONE'}

def approve(payload:dict):
 init_db(); did=str(payload.get('decision_id') or ''); reviewer=str(payload.get('reviewer') or '').strip(); action=str(payload.get('action') or '').upper(); rationale=str(payload.get('rationale') or '').strip()
 if not did or not reviewer or action not in ('APPROVE','REJECT','REVOKE') or not rationale:return {'ok':False,'status':'INVALID','error':'decision_id_reviewer_action_rationale_required','production_effect':'NONE'}
 with _conn() as c:r=c.execute('SELECT * FROM strategy_promotion_decisions WHERE decision_id=?',(did,)).fetchone()
 if not r:return {'ok':False,'status':'NOT_FOUND','production_effect':'NONE'}
 state={'APPROVE':'APPROVED','REJECT':'REJECTED','REVOKE':'REVOKED'}[action]; now=_now(); body={'decision_id':did,'action':action,'approval_state':state,'reviewer':reviewer,'rationale':rationale,'observed_at':now,'manual_approval_only':True,'production_effect':'NONE'}; ih=_hash(body); aid=str(uuid.uuid4())
 with _conn() as c:
  c.execute('INSERT INTO strategy_promotion_approvals VALUES(?,?,?,?,?,?,?,?,?,?,?)',(aid,did,action,reviewer,rationale,now,_json(body),SCHEMA_VERSION,VERSION,ih,now))
  c.execute('UPDATE strategy_promotion_decisions SET approval_state=?,reviewer=?,rationale=? WHERE decision_id=?',(state,reviewer,rationale,did))
 return {'ok':True,'status':'RECORDED','approval_id':aid,**body,'integrity_hash':ih}

def history(limit=100):
 init_db()
 with _conn() as c:rows=c.execute('SELECT * FROM strategy_promotion_decisions ORDER BY observed_at DESC LIMIT ?',(max(1,min(int(limit),1000)),)).fetchall()
 out=[]
 for r in rows:
  d=dict(r); d['decision']=json.loads(d.pop('decision_json')); out.append(d)
 return out

def status():
 init_db()
 with _conn() as c:
  candidates=c.execute('SELECT COUNT(*) n FROM strategy_promotion_candidates').fetchone()['n']; decisions=c.execute('SELECT COUNT(*) n FROM strategy_promotion_decisions').fetchone()['n']; approvals=c.execute('SELECT COUNT(*) n FROM strategy_promotion_approvals').fetchone()['n']
 return {'status':'READY','engine':'STRATEGY_PROMOTION_GOVERNANCE','build_version':VERSION,'schema_version':SCHEMA_VERSION,'promotion_states':PROMOTION_STATES,'approval_states':APPROVAL_STATES,'candidate_count':candidates,'decision_count':decisions,'approval_count':approvals,'automatic_promotion_enabled':False,'manual_approval_required':True,'recommendation_mutation_enabled':False,'confidence_mutation_enabled':False,'broker_order_submission_enabled':False,'production_effect':'NONE'}

def dashboard():return {'ok':True,'status':'READY','safety':status(),'recent_decisions':history(25)}
