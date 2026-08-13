"""APEX 18.1.3 — Portfolio Outcome Attribution & Replay.

Persists complete advisory portfolio recommendations and grades them after the
cash close using the exact captured structures. No broker authority.
"""
from __future__ import annotations
import datetime as dt, json, os, sqlite3
from typing import Any, Callable, Dict, List, Optional
from .refusal_replay import grade_refusal, _bar_ts_ms, _parse_ts, ET

VERSION="18.1.3_PORTFOLIO_OUTCOME_ATTRIBUTION"

class PortfolioOutcomeStore:
    def __init__(self, db_path: Optional[str]=None):
        self.db_path=db_path or os.getenv("DB_PATH","apex_tracking.db"); self._init()
    def _connect(self):
        c=sqlite3.connect(self.db_path); c.row_factory=sqlite3.Row; return c
    def _init(self):
        with self._connect() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS premium_portfolio_outcomes(
              id INTEGER PRIMARY KEY AUTOINCREMENT, portfolio_key TEXT UNIQUE NOT NULL,
              ts TEXT NOT NULL, session_date TEXT NOT NULL, ticker TEXT NOT NULL,
              portfolio_json TEXT NOT NULL, state TEXT NOT NULL, modeled_pnl REAL,
              outcome TEXT, attribution_json TEXT, notes TEXT, graded_at TEXT)""")
    def record(self,ticker:str,portfolio:Dict[str,Any],observed_at:Optional[dt.datetime]=None)->Dict[str,Any]:
        now=observed_at or dt.datetime.now(dt.timezone.utc)
        if isinstance(now,str): now=dt.datetime.fromisoformat(now)
        if now.tzinfo is None: now=now.replace(tzinfo=dt.timezone.utc)
        selected=portfolio.get("selected_positions") or []
        key_parts=[now.astimezone(ET).date().isoformat(),ticker.upper()]
        for p in selected:
            key_parts += [str(p.get("strategy")),str(p.get("contracts")),json.dumps(p.get("candidate") or {},sort_keys=True)]
        import hashlib
        key=hashlib.sha256("|".join(key_parts).encode()).hexdigest()
        payload=json.dumps(portfolio,sort_keys=True,default=str)
        with self._connect() as c:
            c.execute("INSERT OR IGNORE INTO premium_portfolio_outcomes(portfolio_key,ts,session_date,ticker,portfolio_json,state) VALUES(?,?,?,?,?,?)",
                      (key,now.isoformat(),now.astimezone(ET).date().isoformat(),ticker.upper(),payload,"PENDING" if selected else "NO_ALLOCATION"))
            row=c.execute("SELECT * FROM premium_portfolio_outcomes WHERE portfolio_key=?",(key,)).fetchone()
        return dict(row) if row else {"portfolio_key":key,"recorded":False}
    def pending(self,limit:int=300)->List[Dict[str,Any]]:
        with self._connect() as c: return [dict(r) for r in c.execute("SELECT * FROM premium_portfolio_outcomes WHERE state='PENDING' ORDER BY id LIMIT ?",(limit,))]
    def grade(self,row_id:int,outcome:str,pnl:Optional[float],attribution:Any,notes:str):
        with self._connect() as c:
            c.execute("UPDATE premium_portfolio_outcomes SET state='GRADED', outcome=?, modeled_pnl=?, attribution_json=?, notes=?, graded_at=? WHERE id=? AND state='PENDING'",
                      (outcome,pnl,json.dumps(attribution,sort_keys=True),notes,dt.datetime.now(dt.timezone.utc).isoformat(),row_id))
    def recent(self,limit:int=100)->List[Dict[str,Any]]:
        with self._connect() as c:
            rows=[dict(r) for r in c.execute("SELECT * FROM premium_portfolio_outcomes ORDER BY id DESC LIMIT ?",(limit,))]
        for r in rows:
            for k in ("portfolio_json","attribution_json"):
                try:r[k[:-5] if k.endswith('_json') else k]=json.loads(r.get(k) or ('{}' if k=='attribution_json' else '{}'))
                except Exception:pass
        return rows
    def scorecard(self)->Dict[str,Any]:
        with self._connect() as c:
            rows=[dict(r) for r in c.execute("SELECT * FROM premium_portfolio_outcomes WHERE state='GRADED'")]
            pending=c.execute("SELECT COUNT(*) FROM premium_portfolio_outcomes WHERE state='PENDING'").fetchone()[0]
        pnls=[float(r['modeled_pnl']) for r in rows if r['modeled_pnl'] is not None]
        wins=sum(1 for x in pnls if x>25); losses=sum(1 for x in pnls if x<-25)
        by={}
        for r in rows:
            try: attrs=json.loads(r.get('attribution_json') or '{}')
            except Exception: attrs={}
            positions = attrs.get('positions', []) if isinstance(attrs, dict) else attrs
            for a in positions:
                s=a.get('strategy','UNKNOWN'); by.setdefault(s,{"count":0,"total_pnl":0.0}); by[s]['count']+=1; by[s]['total_pnl']+=float(a.get('modeled_pnl') or 0)
        for v in by.values(): v['average_pnl']=round(v['total_pnl']/v['count'],2); v['total_pnl']=round(v['total_pnl'],2)
        return {"version":VERSION,"graded":len(rows),"pending":pending,"pending_portfolios":pending,"wins":wins,"losses":losses,
                "win_rate":round(100*wins/len(pnls),1) if pnls else None,"average_modeled_pnl":round(sum(pnls)/len(pnls),2) if pnls else None,
                "total_modeled_pnl":round(sum(pnls),2),"largest_win":max(pnls) if pnls else None,"largest_loss":min(pnls) if pnls else None,"strategy_attribution":by}

def replay_due_portfolios(store:PortfolioOutcomeStore,get_intraday_bars:Callable[...,List[Dict[str,Any]]],*,now_et:Optional[dt.datetime]=None,limit:int=300)->Dict[str,Any]:
    now_et=now_et or dt.datetime.now(ET); graded=deferred=0; outcomes={}; cache={}
    for row in store.pending(limit):
        day=dt.date.fromisoformat(row['session_date'])
        if now_et.date()==day and now_et.hour<16: deferred+=1; continue
        try: portfolio=json.loads(row['portfolio_json']); rec=_parse_ts(row['ts'])
        except Exception: portfolio={}; rec=None
        if rec is None: store.grade(row['id'],'NOT_EXECUTABLE',None,[],"Invalid recommendation timestamp."); graded+=1; continue
        ticker=row['ticker']; cache.setdefault(ticker,list(get_intraday_bars(ticker,5,7) or []))
        end=dt.datetime.combine(day,dt.time(16),tzinfo=ET).astimezone(dt.timezone.utc).timestamp()*1000
        bars=[b for b in cache[ticker] if _bar_ts_ms(b) is not None and rec.timestamp()*1000<=_bar_ts_ms(b)<=end]
        if not bars:
            if now_et.date()<=day+dt.timedelta(days=2): deferred+=1; continue
            store.grade(row['id'],'NO_DATA',None,[],"No forward bars after retry window."); graded+=1; outcomes['NO_DATA']=outcomes.get('NO_DATA',0)+1; continue
        attrs=[]; total=0.0; executable=True
        for p in portfolio.get('selected_positions') or []:
            result=grade_refusal(p.get('candidate') or {},bars); contracts=int(p.get('contracts') or 0)
            pnl=result.get('pnl')
            if pnl is None: executable=False
            cpnl=None if pnl is None else round(float(pnl)*contracts,2)
            if cpnl is not None: total+=cpnl
            attrs.append({"strategy":p.get('strategy'),"contracts":contracts,"modeled_pnl":cpnl,"component_outcome":result.get('outcome'),"metrics":result.get('metrics')})
        outcome='NOT_EXECUTABLE' if not executable else ('PORTFOLIO_WIN' if total>25 else 'PORTFOLIO_LOSS' if total<-25 else 'PORTFOLIO_FLAT')
        store.grade(row['id'],outcome,None if not executable else round(total,2),{'positions': attrs},f"{outcome}; modeled portfolio P&L {total:+.2f}.")
        graded+=1; outcomes[outcome]=outcomes.get(outcome,0)+1
    return {"version":VERSION,"graded":graded,"deferred":deferred,"outcomes":outcomes}
