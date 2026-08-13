"""APEX 18.1.4 — Adaptive Portfolio Allocation Calibration.

Learns bounded advisory allocation parameters from graded portfolio outcomes.
Recommendations are immutable and non-operational until explicitly promoted.
"""
from __future__ import annotations
import datetime as dt, json, os, sqlite3
from typing import Any, Dict, Optional
VERSION="18.1.4_ADAPTIVE_PORTFOLIO_ALLOCATION_CALIBRATION"
DEFAULT={"institutional_score_weight":0.50,"expected_value_weight":0.50,"bull_bear_pair_penalty":0.35,"max_positions":2,"max_contracts_per_strategy":3}
class PortfolioCalibrationStore:
    def __init__(self,db_path:Optional[str]=None): self.db_path=db_path or os.getenv('DB_PATH','apex_tracking.db'); self._init()
    def _c(self): c=sqlite3.connect(self.db_path); c.row_factory=sqlite3.Row; return c
    def _init(self):
        with self._c() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS portfolio_calibration_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, status TEXT NOT NULL, sample_size INTEGER NOT NULL, evidence_json TEXT NOT NULL, recommendation_json TEXT NOT NULL, promoted INTEGER NOT NULL DEFAULT 0, promoted_at TEXT, promoted_by TEXT)""")
    def active_policy(self)->Dict[str,Any]:
        with self._c() as c:r=c.execute("SELECT * FROM portfolio_calibration_runs WHERE promoted=1 ORDER BY promoted_at DESC,id DESC LIMIT 1").fetchone()
        if not r:return {"source":"DEFAULT","run_id":None,**DEFAULT}
        return {"source":"PROMOTED","run_id":r['id'],**json.loads(r['recommendation_json'])}
    def run(self,min_sample:int=20,lookback:int=500)->Dict[str,Any]:
        with self._c() as c: rows=[dict(r) for r in c.execute("SELECT modeled_pnl,attribution_json FROM premium_portfolio_outcomes WHERE state='GRADED' AND modeled_pnl IS NOT NULL ORDER BY id DESC LIMIT ?",(lookback,))]
        by={}; total=len(rows)
        for r in rows:
            try:a=json.loads(r['attribution_json'] or '{}')
            except Exception:a={}
            positions = a.get('positions', []) if isinstance(a, dict) else a
            for x in positions:
                s=x.get('strategy','UNKNOWN'); by.setdefault(s,[]).append(float(x.get('modeled_pnl') or 0))
        stats={s:{"sample_size":len(v),"average_pnl":round(sum(v)/len(v),2),"win_rate":round(100*sum(x>25 for x in v)/len(v),1)} for s,v in by.items() if v}
        active=self.active_policy(); rec={k:active[k] for k in DEFAULT}
        status='INSUFFICIENT_SAMPLE'
        if total>=min_sample:
            status='RECOMMENDATION_READY'
            aggregate=sum(float(r['modeled_pnl']) for r in rows)/total
            # bounded, conservative shifts only
            rec['expected_value_weight']=round(min(.70,max(.35,active['expected_value_weight']+(0.05 if aggregate>0 else -0.05))),2)
            rec['institutional_score_weight']=round(1-rec['expected_value_weight'],2)
            bull=stats.get('BULL_PUT',{}).get('average_pnl',0); bear=stats.get('BEAR_CALL',{}).get('average_pnl',0)
            rec['bull_bear_pair_penalty']=round(min(.60,max(.20,active['bull_bear_pair_penalty']+(0.05 if bull+bear<0 else -0.05))),2)
        evidence={"sample_size":total,"minimum_sample":min_sample,"aggregate_average_pnl":round(sum(float(r['modeled_pnl']) for r in rows)/total,2) if total else None,"strategy_stats":stats}
        with self._c() as c:
            cur=c.execute("INSERT INTO portfolio_calibration_runs(created_at,status,sample_size,evidence_json,recommendation_json) VALUES(?,?,?,?,?)",(dt.datetime.now(dt.timezone.utc).isoformat(),status,total,json.dumps(evidence,sort_keys=True),json.dumps(rec,sort_keys=True))); rid=cur.lastrowid
        return {"version":VERSION,"run_id":rid,"status":status,"evidence":evidence,"recommendation":rec,"operational":False}
    def recent(self,limit:int=20):
        with self._c() as c: rows=[dict(r) for r in c.execute("SELECT * FROM portfolio_calibration_runs ORDER BY id DESC LIMIT ?",(limit,))]
        for r in rows:
            r['evidence']=json.loads(r.pop('evidence_json')); r['recommendation']=json.loads(r.pop('recommendation_json'))
        return rows
    def promote(self,run_id:int,promoted_by:str='operator'):
        with self._c() as c:
            r=c.execute("SELECT * FROM portfolio_calibration_runs WHERE id=?",(run_id,)).fetchone()
            if not r: raise ValueError('Calibration run not found.')
            if r['status']!='RECOMMENDATION_READY': raise ValueError('Only recommendation-ready runs may be promoted.')
            c.execute("UPDATE portfolio_calibration_runs SET promoted=0 WHERE promoted=1")
            ts=dt.datetime.now(dt.timezone.utc).isoformat(); c.execute("UPDATE portfolio_calibration_runs SET promoted=1,promoted_at=?,promoted_by=? WHERE id=?",(ts,promoted_by,run_id))
        return {"run_id":run_id,"promoted":True,"promoted_at":ts,"promoted_by":promoted_by,"policy":self.active_policy()}
