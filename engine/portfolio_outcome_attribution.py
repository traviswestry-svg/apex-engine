"""APEX 18.1.3 — Portfolio Outcome Attribution & Replay.

Persists governed optimizer recommendations, replays each selected structure after
settlement, and attributes modeled portfolio P&L to strategy selection, sizing,
and concentration. Advisory only; no broker authority.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from typing import Any, Callable, Dict, List, Optional

from .refusal_replay import ET, NO_DATA, NOT_EXECUTABLE, grade_refusal, _bar_ts_ms

VERSION = "18.1.3_PORTFOLIO_OUTCOME_ATTRIBUTION"
_SETTLE_HOUR_ET = 16


class PortfolioOutcomeStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("DB_PATH", "apex_tracking.db")
        self._init()

    def _connect(self):
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        directory = os.path.dirname(self.db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with self._connect() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS premium_portfolio_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                session_date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                state TEXT NOT NULL,
                portfolio_json TEXT NOT NULL,
                fingerprint TEXT NOT NULL UNIQUE,
                outcome TEXT,
                modeled_pnl REAL,
                attribution_json TEXT,
                graded_at TEXT,
                grade_source TEXT
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_ppr_session ON premium_portfolio_recommendations(session_date,ticker,outcome)")
            c.commit()

    def record(self, ticker: str, portfolio: Dict[str, Any], *, observed_at: Optional[str] = None) -> Dict[str, Any]:
        now = observed_at or dt.datetime.now(dt.timezone.utc).isoformat()
        session_date = now[:10]
        selected = portfolio.get("selected_positions") or []
        canonical = {
            "session_date": session_date,
            "ticker": ticker,
            "state": portfolio.get("state"),
            "selected": [{
                "strategy": x.get("strategy"), "contracts": x.get("contracts"),
                "candidate": x.get("candidate"), "allocated_risk": x.get("allocated_risk"),
                "portfolio_expected_value": x.get("portfolio_expected_value"),
            } for x in selected],
        }
        fingerprint = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        payload = json.dumps(portfolio, sort_keys=True, separators=(",", ":"), default=str)
        with self._connect() as c:
            c.execute("""INSERT OR IGNORE INTO premium_portfolio_recommendations
                (created_at,session_date,ticker,state,portfolio_json,fingerprint)
                VALUES (?,?,?,?,?,?)""", (now, session_date, ticker, str(portfolio.get("state") or "UNKNOWN"), payload, fingerprint))
            c.commit()
            row = c.execute("SELECT id,outcome FROM premium_portfolio_recommendations WHERE fingerprint=?", (fingerprint,)).fetchone()
        return {"recorded": True, "id": row["id"] if row else None, "already_graded": bool(row and row["outcome"])}

    def pending(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._connect() as c:
            rows = c.execute("SELECT * FROM premium_portfolio_recommendations WHERE outcome IS NULL ORDER BY id LIMIT ?", (max(1, min(limit, 1000)),)).fetchall()
        return [dict(r) for r in rows]

    def grade(self, row_id: int, *, outcome: str, pnl: Optional[float], attribution: Dict[str, Any], source: str = "REPLAY") -> bool:
        with self._connect() as c:
            cur = c.execute("""UPDATE premium_portfolio_recommendations
                SET outcome=?,modeled_pnl=?,attribution_json=?,graded_at=?,grade_source=?
                WHERE id=? AND outcome IS NULL""", (outcome, pnl, json.dumps(attribution, sort_keys=True, default=str), dt.datetime.now(dt.timezone.utc).isoformat(), source, int(row_id)))
            c.commit()
        return cur.rowcount == 1

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as c:
            rows = c.execute("SELECT * FROM premium_portfolio_recommendations ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            d["portfolio"] = json.loads(d.pop("portfolio_json"))
            d.pop("fingerprint", None)
            d["attribution"] = json.loads(d.pop("attribution_json")) if d.get("attribution_json") else None
            out.append(d)
        return out

    def scorecard(self) -> Dict[str, Any]:
        with self._connect() as c:
            rows = c.execute("SELECT outcome,modeled_pnl,attribution_json FROM premium_portfolio_recommendations WHERE outcome IS NOT NULL").fetchall()
            pending = c.execute("SELECT COUNT(*) n FROM premium_portfolio_recommendations WHERE outcome IS NULL").fetchone()["n"]
        pnls = [float(r["modeled_pnl"]) for r in rows if r["modeled_pnl"] is not None]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        by_strategy: Dict[str, Dict[str, float]] = {}
        for r in rows:
            if not r["attribution_json"]:
                continue
            for item in json.loads(r["attribution_json"]).get("positions", []):
                key = str(item.get("strategy") or "UNKNOWN")
                bucket = by_strategy.setdefault(key, {"observations": 0, "modeled_pnl": 0.0})
                bucket["observations"] += 1
                bucket["modeled_pnl"] += float(item.get("modeled_pnl") or 0)
        for bucket in by_strategy.values():
            bucket["modeled_pnl"] = round(bucket["modeled_pnl"], 2)
        return {
            "version": VERSION, "graded_portfolios": len(rows), "pending_portfolios": pending,
            "win_rate_pct": round(100 * len(wins) / len(pnls), 1) if pnls else None,
            "average_modeled_pnl": round(sum(pnls) / len(pnls), 2) if pnls else None,
            "total_modeled_pnl": round(sum(pnls), 2) if pnls else None,
            "largest_win": round(max(wins), 2) if wins else None,
            "largest_loss": round(min(losses), 2) if losses else None,
            "strategy_attribution": by_strategy,
        }


def _candidate_for_replay(position: Dict[str, Any]) -> Dict[str, Any]:
    candidate = dict(position.get("candidate") or {})
    mapping = {"BULL_PUT": "BULL_PUT_CREDIT_SPREAD", "BEAR_CALL": "BEAR_CALL_CREDIT_SPREAD", "IRON_CONDOR": "IRON_CONDOR"}
    candidate["strategy"] = mapping.get(str(position.get("strategy")), candidate.get("strategy"))
    return candidate


def replay_due_portfolios(store: PortfolioOutcomeStore, get_intraday_bars: Callable[..., List[Dict[str, Any]]], *, now_et: Optional[dt.datetime] = None, limit: int = 200) -> Dict[str, Any]:
    now_et = now_et or dt.datetime.now(ET)
    if now_et.tzinfo is None:
        now_et = now_et.replace(tzinfo=ET)
    rows = store.pending(limit)
    cache: Dict[str, List[Dict[str, Any]]] = {}
    graded = deferred = 0
    outcomes: Dict[str, int] = {}
    for row in rows:
        try:
            session_date = dt.date.fromisoformat(row["session_date"])
        except Exception:
            store.grade(row["id"], outcome=NOT_EXECUTABLE, pnl=None, attribution={"reason": "invalid session date"})
            graded += 1; outcomes[NOT_EXECUTABLE] = outcomes.get(NOT_EXECUTABLE, 0) + 1; continue
        if not (now_et.date() > session_date or (now_et.date() == session_date and now_et.hour >= _SETTLE_HOUR_ET)):
            deferred += 1; continue
        ticker = row["ticker"] or "SPX"
        if ticker not in cache:
            try: cache[ticker] = list(get_intraday_bars(ticker, 5, 7) or [])
            except Exception: cache[ticker] = []
        try: portfolio = json.loads(row["portfolio_json"])
        except Exception: portfolio = {}
        created = dt.datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
        if created.tzinfo is None: created = created.replace(tzinfo=dt.timezone.utc)
        close_et = dt.datetime.combine(session_date, dt.time(16, 0), tzinfo=ET)
        start_ms, end_ms = created.timestamp() * 1000, close_et.astimezone(dt.timezone.utc).timestamp() * 1000
        bars = [b for b in cache[ticker] if _bar_ts_ms(b) is not None and start_ms <= _bar_ts_ms(b) <= end_ms]
        if not bars:
            if now_et.date() <= session_date + dt.timedelta(days=2): deferred += 1; continue
            store.grade(row["id"], outcome=NO_DATA, pnl=None, attribution={"positions": [], "reason": "no forward bars"})
            graded += 1; outcomes[NO_DATA] = outcomes.get(NO_DATA, 0) + 1; continue
        positions=[]; total=0.0; executable=True
        for position in portfolio.get("selected_positions") or []:
            result = grade_refusal(_candidate_for_replay(position), bars)
            contracts = max(0, int(position.get("contracts") or 0))
            per_contract = result.get("pnl")
            modeled = round(float(per_contract) * contracts, 2) if per_contract is not None else None
            if modeled is None: executable=False
            else: total += modeled
            positions.append({"strategy": position.get("strategy"), "contracts": contracts, "per_contract_pnl": per_contract, "modeled_pnl": modeled, "path_outcome": result.get("outcome"), "metrics": result.get("metrics")})
        outcome = NOT_EXECUTABLE if not executable else "PORTFOLIO_WIN" if total > 25 else "PORTFOLIO_LOSS" if total < -25 else "PORTFOLIO_FLAT"
        attribution = {"positions": positions, "expected_value": (portfolio.get("portfolio_summary") or {}).get("expected_value"), "actual_vs_expected": round(total - float((portfolio.get("portfolio_summary") or {}).get("expected_value") or 0), 2) if executable else None}
        store.grade(row["id"], outcome=outcome, pnl=round(total,2) if executable else None, attribution=attribution)
        graded += 1; outcomes[outcome] = outcomes.get(outcome, 0) + 1
    return {"version": VERSION, "examined": len(rows), "graded": graded, "deferred": deferred, "outcomes": outcomes}
