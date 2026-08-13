"""APEX 18.1.6 — Premium Portfolio Risk Governor.

Deterministic, advisory risk authority for premium portfolios. It combines the
portfolio optimizer, execution-reality assessment and day-level risk state into
an explicit ALLOW / REDUCE / BLOCK decision. It never routes orders.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, os, sqlite3
from typing import Any, Dict, Optional

VERSION = "18.1.6_PORTFOLIO_RISK_GOVERNOR"

def _f(v: Any, d: float = 0.0) -> float:
    try: return d if v is None else float(v)
    except (TypeError, ValueError): return d

def _i(v: Any, d: int = 0) -> int:
    try: return d if v is None else int(v)
    except (TypeError, ValueError): return d

def _b(v: Any) -> bool:
    return str(v).strip().lower() in {"1","true","yes","on"}

def evaluate_portfolio_risk(portfolio: Dict[str, Any], execution_reality: Optional[Dict[str, Any]] = None, *,
                            daily_realized_pnl: float = 0.0, open_risk: float = 0.0,
                            trades_today: int = 0, losses_today: int = 0,
                            account_size: Optional[float] = None,
                            max_daily_loss: Optional[float] = None,
                            max_total_open_risk: Optional[float] = None,
                            max_trades_per_day: Optional[int] = None,
                            loss_lockout_count: Optional[int] = None) -> Dict[str, Any]:
    summary = portfolio.get("portfolio_summary") or {}
    selected = list(portfolio.get("selected_positions") or [])
    acct = max(0.0, _f(account_size, _f(os.getenv("ACCOUNT_SIZE"), 0.0)))
    daily_limit = max(0.0, _f(max_daily_loss, _f(os.getenv("TRADE_MAX_DAILY_LOSS"), 2500.0)))
    risk_limit = max(0.0, _f(max_total_open_risk, _f(os.getenv("APEX_MAX_TOTAL_OPEN_RISK"), 4000.0)))
    trade_limit = max(1, _i(max_trades_per_day, _i(os.getenv("TRADE_MAX_TRADES_PER_DAY"), 3)))
    loss_limit = max(1, _i(loss_lockout_count, _i(os.getenv("TRADE_LOSS_LOCKOUT_COUNT"), 2)))
    proposed_risk = max(0.0, _f(summary.get("maximum_defined_risk")))
    proposed_ev = _f(summary.get("expected_value"))
    current_open = max(0.0, _f(open_risk))
    total_after = current_open + proposed_risk
    day_pnl = _f(daily_realized_pnl)
    remaining_loss = max(0.0, daily_limit + min(0.0, day_pnl))
    blockers, warnings = [], []
    if portfolio.get("state") != "PORTFOLIO_READY" or not selected: blockers.append("No governed premium portfolio is ready.")
    if day_pnl <= -daily_limit: blockers.append("Maximum daily loss has been reached.")
    if _i(losses_today) >= loss_limit: blockers.append("Consecutive/daily loss lockout is active.")
    if _i(trades_today) >= trade_limit: blockers.append("Maximum trade count for the session has been reached.")
    if proposed_risk <= 0: blockers.append("Proposed portfolio defined risk cannot be verified.")
    if total_after > risk_limit: blockers.append("Total open risk would exceed the governed portfolio limit.")
    if proposed_risk > remaining_loss: blockers.append("Proposed risk exceeds remaining daily-loss capacity.")
    if proposed_ev <= 0: blockers.append("Portfolio expected value is not positive.")
    er = execution_reality or {}
    if er and er.get("state") != "EXECUTABLE": blockers.append("Execution Reality has no executable recommendation.")
    if acct and total_after > acct * 0.06: blockers.append("Total open risk would exceed the 6% account hard cap.")
    if not blockers and total_after > 0.8 * risk_limit: warnings.append("Risk utilization will exceed 80% of the governed limit.")
    if not blockers and remaining_loss and proposed_risk > 0.75 * remaining_loss: warnings.append("The proposal consumes more than 75% of remaining daily-loss capacity.")
    utilization = 100.0 * total_after / risk_limit if risk_limit else 100.0
    state = "BLOCKED" if blockers else "REDUCE" if warnings else "APPROVED"
    max_additional = max(0.0, min(risk_limit-total_after, remaining_loss-proposed_risk))
    return {
        "version": VERSION, "state": state, "approved": state in {"APPROVED","REDUCE"},
        "new_entries_allowed": state in {"APPROVED","REDUCE"}, "risk_increase_allowed": state == "APPROVED",
        "risk_reduction_allowed": True, "proposed_portfolio_risk": round(proposed_risk,2),
        "open_risk_before": round(current_open,2), "open_risk_after": round(total_after,2),
        "risk_utilization_pct": round(utilization,1), "remaining_daily_loss_capacity": round(remaining_loss,2),
        "max_additional_risk_after": round(max_additional,2), "trades_today": _i(trades_today), "losses_today": _i(losses_today),
        "limits": {"max_daily_loss":daily_limit,"max_total_open_risk":risk_limit,"max_trades_per_day":trade_limit,
                   "loss_lockout_count":loss_limit,"account_size":acct or None,"account_hard_cap_pct":6.0},
        "blockers": blockers, "warnings": warnings,
        "advisory_only": True, "execution_authority": False,
        "governance_note": "This governor may block or reduce a recommendation but cannot transmit an order."
    }

class RiskGovernorStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("DB_PATH", "apex_tracking.db"); self._init()
    def _connect(self):
        c=sqlite3.connect(self.db_path); c.row_factory=sqlite3.Row; return c
    def _init(self):
        with self._connect() as c:c.execute("""CREATE TABLE IF NOT EXISTS premium_risk_governor_decisions(
          id INTEGER PRIMARY KEY AUTOINCREMENT, decision_key TEXT UNIQUE NOT NULL, ts TEXT NOT NULL,
          ticker TEXT NOT NULL, state TEXT NOT NULL, approved INTEGER NOT NULL, payload_json TEXT NOT NULL)""")
    def record(self,ticker:str,payload:Dict[str,Any],observed_at:Optional[dt.datetime]=None):
        now=observed_at or dt.datetime.now(dt.timezone.utc)
        if now.tzinfo is None: now=now.replace(tzinfo=dt.timezone.utc)
        raw=json.dumps({"ticker":ticker.upper(),"minute":now.replace(second=0,microsecond=0).isoformat(),"state":payload.get("state"),"risk":payload.get("proposed_portfolio_risk")},sort_keys=True)
        key=hashlib.sha256(raw.encode()).hexdigest()
        with self._connect() as c:
            c.execute("INSERT OR IGNORE INTO premium_risk_governor_decisions(decision_key,ts,ticker,state,approved,payload_json) VALUES(?,?,?,?,?,?)",
                      (key,now.isoformat(),ticker.upper(),payload.get("state") or "UNKNOWN",1 if payload.get("approved") else 0,json.dumps(payload,sort_keys=True,default=str)))
            r=c.execute("SELECT * FROM premium_risk_governor_decisions WHERE decision_key=?",(key,)).fetchone()
        return dict(r) if r else {"decision_key":key}
    def recent(self,limit=100):
        with self._connect() as c: rows=c.execute("SELECT * FROM premium_risk_governor_decisions ORDER BY id DESC LIMIT ?",(max(1,min(int(limit),500)),)).fetchall()
        return [{**dict(r),"payload":json.loads(r["payload_json"])} for r in rows]
