"""APEX 47.0.4 — automatic, explicit outcome grading."""
from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from engine.evidence_pipeline import _connect, DEFAULT_DB, readiness
VERSION='69.9.5'; SCHEMA_VERSION='apex.outcome_grader.v2'; DEFAULT_HORIZON=int(os.getenv('APEX_GRADING_HORIZON_SECONDS','300'))
def _dt(v): return datetime.fromisoformat(str(v).replace('Z','+00:00'))
def run_grader(path: str|Path=DEFAULT_DB,horizon_seconds:int=DEFAULT_HORIZON,limit:int=500)->dict[str,Any]:
 now=datetime.now(timezone.utc); counts={'graded':0,'excluded':0,'not_matured':0,'errors':0}
 with _connect(path) as c:
  rows=c.execute("SELECT * FROM decisions WHERE status='PENDING' ORDER BY observed_at LIMIT ?",(limit,)).fetchall()
  for r in rows:
   did=r['decision_id']
   try:
    observed=_dt(r['observed_at']); age=(now-observed).total_seconds()
    reason=None
    if not int(r['learning_eligible']): reason='NON_ACTIONABLE'
    elif str(r['session']).upper() in {'CLOSED','MARKET_CLOSED','AFTER_HOURS'}: reason='MARKET_CLOSED'
    elif r['entry_price'] is None: reason='MISSING_ENTRY_PRICE'
    elif age < horizon_seconds: counts['not_matured']+=1; continue
    if reason:
     c.execute("INSERT OR IGNORE INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json) VALUES(?,?,?,?,?,?)",(did,now.isoformat(),'EXCLUDED',reason,horizon_seconds,json.dumps({'reason':reason}))); c.execute("UPDATE decisions SET status='EXCLUDED' WHERE decision_id=?",(did,)); counts['excluded']+=1; continue
    end=(observed.timestamp()+horizon_seconds)
    prices=c.execute("SELECT observed_at,price FROM price_samples WHERE ticker=? AND observed_at>=? AND observed_at<=? ORDER BY observed_at",(r['ticker'],r['observed_at'],datetime.fromtimestamp(end,timezone.utc).isoformat())).fetchall()
    if not prices:
     c.execute("INSERT OR IGNORE INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json) VALUES(?,?,?,?,?,?)",(did,now.isoformat(),'EXCLUDED','MISSING_FORWARD_PRICE',horizon_seconds,json.dumps({'reason':'MISSING_FORWARD_PRICE'}))); c.execute("UPDATE decisions SET status='EXCLUDED' WHERE decision_id=?",(did,)); counts['excluded']+=1; continue
    entry=float(r['entry_price']); vals=[float(x['price']) for x in prices]; final_row=prices[-1]; final=float(final_row['price']); bullish=str(r['direction']).upper()=='BULLISH'; move=(final-entry)*(1 if bullish else -1); mfe=max((p-entry)*(1 if bullish else -1) for p in vals); mae=min((p-entry)*(1 if bullish else -1) for p in vals); won=move>0
    outcome={'won':won,'direction_correct':won,'entry_price':entry,'forward_price':final,'forward_observed_at':final_row['observed_at'],'directional_move':round(move,4),'mfe':round(mfe,4),'mae':round(mae,4),'horizon_seconds':horizon_seconds,'window_start_at':r['observed_at'],'window_end_at':datetime.fromtimestamp(end,timezone.utc).isoformat(),'price_sample_count':len(prices),'price_query_window_enforced':True}
    c.execute("INSERT OR IGNORE INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json) VALUES(?,?,?,?,?,?)",(did,now.isoformat(),'GRADED',None,horizon_seconds,json.dumps(outcome))); c.execute("UPDATE decisions SET status='GRADED' WHERE decision_id=?",(did,)); counts['graded']+=1
    try:
     # Observational NO_TRADE thesis grading is diagnostic only. It must never
     # feed adaptive calibration/promotion as though an executed trade occurred.
     snap=json.loads(r['snapshot_json'])
     if not bool(snap.get('observational_only')):
      from engine.adaptive_learning import record_outcome
      record_outcome({'ticker':r['ticker'],'direction':r['direction'],'confidence':r['confidence'],'won':won,'realized_return':move,'horizon_seconds':horizon_seconds,'features':snap.get('feature_vector') or {},'metadata':{'decision_id':did,'source':'APEX_47_AUTO_GRADER'}})
    except Exception: pass
   except Exception: counts['errors']+=1
 try:
  from engine.decision_outcome_attribution import grade_pending
  attribution=grade_pending(path,horizon_seconds=horizon_seconds,limit=limit,now=now)
 except Exception as exc:
  attribution={'graded':0,'errors':1,'status':'DEGRADED','error':type(exc).__name__}
 try:
  from engine.trigger_observatory import sync_canonical_outcomes
  trigger_linkage=sync_canonical_outcomes(evidence_path=str(path))
 except Exception as exc:
  trigger_linkage={'ok':False,'status':'DEGRADED','linked':0,'error':type(exc).__name__,'execution_authority':False}
 return {'ok':True,**counts,'processed':sum(counts.values()),'horizon_seconds':horizon_seconds,'readiness':readiness(path),'attribution':attribution,'trigger_outcome_linkage':trigger_linkage,'schema_version':SCHEMA_VERSION,'engine_version':VERSION,'execution_authority':False}
def horizon_integrity(path: str|Path=DEFAULT_DB)->dict[str,Any]:
 expected=300
 result={'ok':True,'schema_version':'apex.outcome_grader_horizon_integrity.v1','engine_version':VERSION,
         'configured_default_horizon_seconds':DEFAULT_HORIZON,'expected_canonical_horizon_seconds':expected,
         'configured_is_expected':DEFAULT_HORIZON==expected,'price_query_window_contract':'observed_at >= decision_observed_at AND observed_at <= decision_observed_at + horizon_seconds',
         'execution_authority':False,'production_effect':'OBSERVATIONAL_ONLY'}
 if not Path(path).exists(): return {**result,'status':'MISSING_EVIDENCE_DB','stored_grade_count':0}
 try:
  with _connect(path) as c:
   rows=c.execute("SELECT g.decision_id,g.status,g.horizon_seconds,g.outcome_json,d.observed_at FROM grading_results g LEFT JOIN decisions d ON d.decision_id=g.decision_id").fetchall()
 except Exception as exc:
  return {**result,'status':'DEGRADED','error':f'{type(exc).__name__}: {exc}'}
 horizon_counts={}; stored_mismatch=0; outcome_mismatch=0; forward_ts_available=0; forward_ts_in_window=0; forward_ts_out_of_window=0; unreadable=0
 for r in rows:
  h=r['horizon_seconds']; key=str(h if h is not None else 'UNKNOWN'); horizon_counts[key]=horizon_counts.get(key,0)+1
  if h is not None and int(h)!=expected: stored_mismatch+=1
  try: out=json.loads(r['outcome_json'] or '{}') or {}
  except Exception: unreadable+=1; continue
  oh=out.get('horizon_seconds')
  if oh is not None and int(oh)!=int(h if h is not None else expected): outcome_mismatch+=1
  fwd=out.get('forward_observed_at')
  if fwd and r['observed_at'] and h is not None:
   forward_ts_available+=1
   try:
    start=_dt(r['observed_at']); finish=_dt(fwd); elapsed=(finish-start).total_seconds()
    if 0<=elapsed<=int(h): forward_ts_in_window+=1
    else: forward_ts_out_of_window+=1
   except Exception: unreadable+=1
 status='VERIFIED' if DEFAULT_HORIZON==expected and stored_mismatch==0 and outcome_mismatch==0 and forward_ts_out_of_window==0 else 'DEGRADED'
 return {**result,'status':status,'stored_grade_count':len(rows),'stored_horizon_counts':horizon_counts,
         'stored_horizon_mismatch_count':stored_mismatch,'outcome_horizon_mismatch_count':outcome_mismatch,
         'forward_timestamp_available_count':forward_ts_available,'forward_timestamp_in_window_count':forward_ts_in_window,
         'forward_timestamp_out_of_window_count':forward_ts_out_of_window,'legacy_forward_timestamp_unavailable_count':max(0,len(rows)-forward_ts_available),
         'unreadable_outcome_count':unreadable,'historical_forward_timestamp_verification_complete':forward_ts_available==len(rows) if rows else True}

def summary(path: str|Path=DEFAULT_DB): return {'ok':True,'readiness':readiness(path),'default_horizon_seconds':DEFAULT_HORIZON,'horizon_integrity':horizon_integrity(path),'schema_version':SCHEMA_VERSION,'engine_version':VERSION}
