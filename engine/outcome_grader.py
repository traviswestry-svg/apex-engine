"""APEX 47.0.4 — automatic, explicit outcome grading."""
from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from engine.evidence_pipeline import _connect, DEFAULT_DB, readiness
VERSION='68.6.0'; SCHEMA_VERSION='apex.outcome_grader.v1'; DEFAULT_HORIZON=int(os.getenv('APEX_GRADING_HORIZON_SECONDS','300'))
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
    entry=float(r['entry_price']); vals=[float(x['price']) for x in prices]; final=vals[-1]; bullish=str(r['direction']).upper()=='BULLISH'; move=(final-entry)*(1 if bullish else -1); mfe=max((p-entry)*(1 if bullish else -1) for p in vals); mae=min((p-entry)*(1 if bullish else -1) for p in vals); won=move>0
    outcome={'won':won,'direction_correct':won,'entry_price':entry,'forward_price':final,'directional_move':round(move,4),'mfe':round(mfe,4),'mae':round(mae,4),'horizon_seconds':horizon_seconds}
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
 return {'ok':True,**counts,'processed':sum(counts.values()),'horizon_seconds':horizon_seconds,'readiness':readiness(path),'attribution':attribution,'schema_version':SCHEMA_VERSION,'engine_version':VERSION,'execution_authority':False}
def summary(path: str|Path=DEFAULT_DB): return {'ok':True,'readiness':readiness(path),'default_horizon_seconds':DEFAULT_HORIZON,'schema_version':SCHEMA_VERSION,'engine_version':VERSION}
