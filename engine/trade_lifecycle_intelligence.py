"""APEX 18.2.2 — Trade Lifecycle Intelligence.
Advisory monitoring for confirmed positions; never routes or modifies orders.
"""
from __future__ import annotations
import datetime as dt, json, os, sqlite3
from typing import Any, Dict, Optional
VERSION="18.2.2_TRADE_LIFECYCLE_INTELLIGENCE"

def _f(v,d=0.0):
    try:return float(v)
    except Exception:return d
class LifecycleStore:
    def __init__(self,db_path:Optional[str]=None): self.db_path=db_path or os.getenv("DB_PATH","apex_tracking.db"); self._init()
    def _c(self): c=sqlite3.connect(self.db_path,timeout=10); c.row_factory=sqlite3.Row; return c
    def _init(self):
        with self._c() as c:c.execute("""CREATE TABLE IF NOT EXISTS trade_lifecycle_events(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,position_id TEXT NOT NULL,action TEXT NOT NULL,state_json TEXT NOT NULL,rationale_json TEXT NOT NULL)""")
    def record(self,position_id:str,result:Dict[str,Any])->Dict[str,Any]:
        ts=dt.datetime.now(dt.timezone.utc).isoformat()
        with self._c() as c:cur=c.execute("INSERT INTO trade_lifecycle_events(created_at,position_id,action,state_json,rationale_json) VALUES(?,?,?,?,?)",(ts,position_id,result["action"],json.dumps(result.get("state",{}),default=str),json.dumps(result.get("rationale",[]),default=str)))
        return {"id":cur.lastrowid,"created_at":ts,"position_id":position_id,"action":result["action"]}
    def recent(self,limit=100):
        with self._c() as c:return [dict(r) for r in c.execute("SELECT * FROM trade_lifecycle_events ORDER BY id DESC LIMIT ?",(max(1,min(int(limit),1000)),)).fetchall()]

def evaluate_trade_lifecycle(position:Dict[str,Any], market:Dict[str,Any], *, now:Optional[dt.datetime]=None)->Dict[str,Any]:
    now=now or dt.datetime.now(dt.timezone.utc); entry=_f(position.get("entry_credit") or position.get("entry_price")); mark=_f(position.get("current_debit") or position.get("mark")); max_loss=max(_f(position.get("max_loss"),1),1)
    pnl=_f(position.get("unrealized_pnl"), (entry-mark)*100*_f(position.get("contracts"),1)); pnl_pct=pnl/max_loss
    thesis_ok=bool(market.get("thesis_valid",True)); execution_ok=bool(market.get("execution_quality_ok",True)); regime_shift=bool(market.get("regime_shift",False)); short_breach=bool(market.get("short_strike_breached",False)); minutes_left=_f(market.get("minutes_to_close"),999)
    rationale=[]; action="HOLD"; urgency="NORMAL"
    if short_breach or not thesis_ok:
        action="EXIT"; urgency="IMMEDIATE"; rationale.append("Original trade thesis is invalid or a protected short strike has been breached.")
    elif pnl_pct <= -0.5 or not execution_ok:
        action="REDUCE"; urgency="HIGH"; rationale.append("Loss or execution deterioration exceeds governed tolerance.")
    elif regime_shift:
        action="PROTECT"; urgency="HIGH"; rationale.append("Market regime changed materially after entry.")
    elif pnl_pct >= 0.70:
        action="TAKE_PROFIT"; urgency="HIGH"; rationale.append("Position has captured at least 70% of defined risk-adjusted objective.")
    elif minutes_left <= 20:
        action="EXIT"; urgency="HIGH"; rationale.append("Expiration/close proximity materially increases gamma and liquidity risk.")
    else:rationale.append("Thesis, execution quality, and risk remain within governed limits.")
    return {"version":VERSION,"position_id":str(position.get("position_id") or position.get("id") or "UNKNOWN"),"action":action,"urgency":urgency,"state":{"unrealized_pnl":round(pnl,2),"pnl_to_max_loss":round(pnl_pct,4),"thesis_valid":thesis_ok,"regime_shift":regime_shift,"short_strike_breached":short_breach,"minutes_to_close":minutes_left},"rationale":rationale,"next_review_seconds":15 if urgency in {"IMMEDIATE","HIGH"} else 60,"advisory_only":True,"broker_action":False,"generated_at":now.isoformat()}
