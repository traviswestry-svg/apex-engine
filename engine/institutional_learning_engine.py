"""APEX 18.2.0 — Institutional Learning Engine.

Governed, advisory learning over validated premium decisions and outcomes.  The
engine never changes trade decisions directly: it produces bounded evidence and
operator-reviewable recommendations.
"""
from __future__ import annotations
import datetime as dt, json, os, sqlite3, statistics
from typing import Any, Dict, Iterable, List, Optional

VERSION = "18.2.0_INSTITUTIONAL_LEARNING_ENGINE"


def _j(v: Any) -> str: return json.dumps(v, sort_keys=True, separators=(",", ":"), default=str)
def _loads(v: Any, d: Any) -> Any:
    try: return json.loads(v) if isinstance(v, str) else (v if v is not None else d)
    except Exception: return d

def market_fingerprint(context: Dict[str, Any]) -> Dict[str, Any]:
    """Create a stable, low-cardinality market-state fingerprint."""
    return {
        "ticker": str(context.get("ticker") or "SPX").upper(),
        "regime": str(context.get("premium_regime") or context.get("regime") or "UNKNOWN").upper(),
        "direction": str(context.get("direction") or context.get("bias") or "NEUTRAL").upper(),
        "auction": str(context.get("auction_state") or context.get("auction") or "UNKNOWN").upper(),
        "gamma": str(context.get("gamma_regime") or context.get("gamma") or "UNKNOWN").upper(),
        "volatility": str(context.get("vix_regime") or context.get("volatility_regime") or "UNKNOWN").upper(),
        "time_bucket": str(context.get("time_bucket") or "UNKNOWN").upper(),
    }

class LearningStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("DB_PATH", "apex_tracking.db")
        self._init()
    def _c(self):
        c=sqlite3.connect(self.db_path, timeout=10); c.row_factory=sqlite3.Row; return c
    def _init(self):
        with self._c() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS institutional_learning_samples(
              id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
              ticker TEXT NOT NULL, strategy TEXT NOT NULL, fingerprint_json TEXT NOT NULL,
              features_json TEXT NOT NULL, outcome TEXT, pnl REAL, source TEXT,
              UNIQUE(ticker,strategy,fingerprint_json,created_at))""")
            c.execute("""CREATE TABLE IF NOT EXISTS institutional_learning_runs(
              id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
              sample_count INTEGER NOT NULL, result_json TEXT NOT NULL)""")
    def record(self, ticker: str, strategy: str, context: Dict[str,Any], *, outcome: Optional[str]=None,
               pnl: Optional[float]=None, source: str="SYSTEM", observed_at: Optional[dt.datetime]=None) -> Dict[str,Any]:
        ts=(observed_at or dt.datetime.now(dt.timezone.utc)).isoformat()
        fp=market_fingerprint({**context,"ticker":ticker})
        with self._c() as c:
            cur=c.execute("INSERT INTO institutional_learning_samples(created_at,ticker,strategy,fingerprint_json,features_json,outcome,pnl,source) VALUES(?,?,?,?,?,?,?,?)",
                (ts,ticker.upper(),strategy.upper(),_j(fp),_j(context),outcome,float(pnl) if pnl is not None else None,source[:40]))
        return {"id":cur.lastrowid,"created_at":ts,"fingerprint":fp,"strategy":strategy.upper(),"outcome":outcome,"pnl":pnl}
    def grade(self,row_id:int, outcome:str,pnl:float,source:str="OPERATOR") -> bool:
        with self._c() as c:
            cur=c.execute("UPDATE institutional_learning_samples SET outcome=?,pnl=?,source=? WHERE id=?",(outcome.upper(),float(pnl),source[:40],row_id))
        return cur.rowcount==1
    def recent(self,limit:int=100)->List[Dict[str,Any]]:
        with self._c() as c: rows=c.execute("SELECT * FROM institutional_learning_samples ORDER BY id DESC LIMIT ?",(max(1,min(limit,1000)),)).fetchall()
        return [dict(r) | {"fingerprint":_loads(r["fingerprint_json"],{}),"features":_loads(r["features_json"],{})} for r in rows]
    def analyze(self,min_sample:int=20,lookback:int=1000)->Dict[str,Any]:
        with self._c() as c: rows=c.execute("SELECT * FROM institutional_learning_samples WHERE pnl IS NOT NULL ORDER BY id DESC LIMIT ?",(max(1,lookback),)).fetchall()
        groups: Dict[tuple,List[float]]={}
        for r in rows:
            fp=_loads(r["fingerprint_json"],{})
            key=(r["strategy"],fp.get("regime"),fp.get("direction"),fp.get("volatility"))
            groups.setdefault(key,[]).append(float(r["pnl"]))
        patterns=[]
        for key, vals in groups.items():
            wins=sum(v>0 for v in vals); avg=sum(vals)/len(vals)
            patterns.append({"strategy":key[0],"regime":key[1],"direction":key[2],"volatility":key[3],"samples":len(vals),"win_rate":round(wins/len(vals),4),"average_pnl":round(avg,2),"total_pnl":round(sum(vals),2),"status":"ACTIONABLE" if len(vals)>=min_sample else "DEVELOPING"})
        patterns.sort(key=lambda x:(x["status"]=="ACTIONABLE",x["average_pnl"],x["samples"]),reverse=True)
        result={"version":VERSION,"advisory_only":True,"sample_count":len(rows),"min_sample":min_sample,"readiness":"READY" if len(rows)>=min_sample else "DEVELOPING","patterns":patterns,"best_pattern":patterns[0] if patterns else None,"generated_at":dt.datetime.now(dt.timezone.utc).isoformat()}
        with self._c() as c: c.execute("INSERT INTO institutional_learning_runs(created_at,sample_count,result_json) VALUES(?,?,?)",(result["generated_at"],len(rows),_j(result)))
        return result

def build_learning_intelligence(store: LearningStore, current_context: Optional[Dict[str,Any]]=None, *, min_sample:int=20)->Dict[str,Any]:
    result=store.analyze(min_sample=min_sample)
    if current_context:
        fp=market_fingerprint(current_context); matches=[]
        for p in result["patterns"]:
            score=sum([p.get("regime")==fp.get("regime"),p.get("direction")==fp.get("direction"),p.get("volatility")==fp.get("volatility")])
            if score: matches.append(dict(p, similarity=round(score/3,3)))
        matches.sort(key=lambda x:(x["similarity"],x["samples"],x["average_pnl"]),reverse=True)
        result["current_fingerprint"]=fp; result["similar_patterns"]=matches[:10]
    return result
