"""APEX 47.0.3 — durable decision/evidence ledger and readiness diagnostics."""
from __future__ import annotations
import json, os, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from .canonical_persistence import connect as canonical_connect
VERSION="47.0.3"; SCHEMA_VERSION="apex.evidence_readiness.v1"; DEFAULT_DB=os.getenv("APEX_EVIDENCE_PIPELINE_DB","apex_evidence_pipeline.db")
def _now(): return datetime.now(timezone.utc).isoformat()
def _connect(path: str|Path=DEFAULT_DB):
 c=canonical_connect(path); c.executescript('''
 CREATE TABLE IF NOT EXISTS decisions(decision_id TEXT PRIMARY KEY,observed_at TEXT NOT NULL,ticker TEXT NOT NULL,session TEXT,direction TEXT,action TEXT,entry_price REAL,confidence REAL,learning_eligible INTEGER NOT NULL,snapshot_json TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'PENDING');
 CREATE TABLE IF NOT EXISTS price_samples(id INTEGER PRIMARY KEY AUTOINCREMENT,ticker TEXT NOT NULL,observed_at TEXT NOT NULL,price REAL NOT NULL);
 CREATE TABLE IF NOT EXISTS grading_results(id INTEGER PRIMARY KEY AUTOINCREMENT,decision_id TEXT NOT NULL UNIQUE,graded_at TEXT NOT NULL,status TEXT NOT NULL,exclusion_reason TEXT,horizon_seconds INTEGER,outcome_json TEXT NOT NULL);
 CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status,observed_at); CREATE INDEX IF NOT EXISTS idx_prices_ticker_time ON price_samples(ticker,observed_at);
 '''); return c
def record_snapshot(snapshot: Mapping[str,Any], path: str|Path=DEFAULT_DB)->bool:
 s=dict(snapshot); did=str(s.get('decision_id') or '');
 if not did: return False
 with _connect(path) as c:
  c.execute("INSERT OR IGNORE INTO decisions(decision_id,observed_at,ticker,session,direction,action,entry_price,confidence,learning_eligible,snapshot_json) VALUES(?,?,?,?,?,?,?,?,?,?)",(did,str(s.get('timestamp') or _now()),str(s.get('ticker') or 'SPX'),str(s.get('session') or 'UNKNOWN'),str(s.get('direction') or 'NEUTRAL'),str(s.get('action') or 'STAND_DOWN'),s.get('entry_reference'),s.get('confidence'),int(bool(s.get('learning_eligible'))),json.dumps(s,default=str)))
  return c.total_changes>0
def record_price(ticker:str, price:Any, observed_at:str|None=None,path: str|Path=DEFAULT_DB)->bool:
 try: p=float(price)
 except (TypeError,ValueError): return False
 with _connect(path) as c: c.execute("INSERT INTO price_samples(ticker,observed_at,price) VALUES(?,?,?)",(ticker.upper(),observed_at or _now(),p))
 return True
def readiness(path: str|Path=DEFAULT_DB)->dict[str,Any]:
 with _connect(path) as c:
  total=c.execute('SELECT COUNT(*) n FROM decisions').fetchone()['n']; actionable=c.execute('SELECT COUNT(*) n FROM decisions WHERE learning_eligible=1').fetchone()['n'];
  graded=c.execute("SELECT COUNT(*) n FROM grading_results WHERE status='GRADED'").fetchone()['n']; excluded=c.execute("SELECT COUNT(*) n FROM grading_results WHERE status='EXCLUDED'").fetchone()['n']; pending=c.execute("SELECT COUNT(*) n FROM decisions WHERE status='PENDING'").fetchone()['n']; samples=c.execute('SELECT COUNT(*) n FROM price_samples').fetchone()['n'];
  lastd=c.execute('SELECT MAX(observed_at) v FROM decisions').fetchone()['v']; lastg=c.execute("SELECT MAX(graded_at) v FROM grading_results WHERE status='GRADED'").fetchone()['v'];
  reasons={r['exclusion_reason']:r['n'] for r in c.execute("SELECT exclusion_reason,COUNT(*) n FROM grading_results WHERE status='EXCLUDED' GROUP BY exclusion_reason") if r['exclusion_reason']}
 if total==0: status='WAITING_FOR_LIVE_DATA'
 elif actionable==0: status='NO_ACTIONABLE_DECISIONS'
 elif pending>0 and samples==0: status='GRADING_WINDOW_NOT_MATURED'
 else: status='HEALTHY'
 return {'ok':True,'status':status,'decisions_recorded':total,'actionable_decisions':actionable,'feature_vectors_stored':actionable,'matured_outcomes':graded+excluded,'graded_outcomes':graded,'excluded_outcomes':excluded,'pending_decisions':pending,'price_samples':samples,'shadow_observations':graded,'last_decision_write':lastd,'last_successful_grade':lastg,'exclusion_reasons':reasons,'schema_version':SCHEMA_VERSION,'engine_version':VERSION,'execution_authority':False}
