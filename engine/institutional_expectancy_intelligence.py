"""APEX 18.1.0 — Institutional Expectancy Intelligence.

Historical market fingerprints, similarity search, regime expectancy, confidence
 decomposition, and drift monitoring for premium-strategy decisions. Advisory
 only: this module never authorizes or submits an order.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .institutional_premium_intelligence import classify_premium_regime, rank_premium_strategies
from .premium_discipline import _extract

VERSION = "18.1.0_INSTITUTIONAL_EXPECTANCY_INTELLIGENCE"
FEATURE_KEYS = (
    "mean_reversion_probability", "expansion_probability", "pin_probability",
    "momentum_probability", "flow_conviction", "overall_score", "vix",
)


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return d if v is None else float(v)
    except (TypeError, ValueError):
        return d


def build_market_fingerprint(last_result: Dict[str, Any], *, observed_at: Optional[str] = None) -> Dict[str, Any]:
    x = _extract(last_result)
    regime = classify_premium_regime(last_result)
    now = observed_at or datetime.now(timezone.utc).isoformat()
    return {
        "observed_at": now,
        "session_date": now[:10],
        "regime": regime["name"],
        "direction": regime["direction"],
        "auction_state": regime["auction_state"],
        "gamma_regime": regime["gamma_regime"],
        "vix_regime": regime["vix_regime"],
        "features": {k: round(_f(x.get(k)), 4) for k in FEATURE_KEYS},
    }


def _category_similarity(a: Any, b: Any) -> float:
    if not a or not b or str(a).upper() == "UNKNOWN" or str(b).upper() == "UNKNOWN":
        return 0.5
    return 1.0 if str(a).upper() == str(b).upper() else 0.0


def fingerprint_similarity(current: Dict[str, Any], historical: Dict[str, Any]) -> float:
    cf, hf = current.get("features") or {}, historical.get("features") or {}
    scales = {
        "mean_reversion_probability": 100, "expansion_probability": 100,
        "pin_probability": 100, "momentum_probability": 100,
        "flow_conviction": 100, "overall_score": 100, "vix": 25,
    }
    numeric = []
    for k, scale in scales.items():
        numeric.append(max(0.0, 1.0 - abs(_f(cf.get(k)) - _f(hf.get(k))) / scale))
    categorical = [
        _category_similarity(current.get("regime"), historical.get("regime")),
        _category_similarity(current.get("direction"), historical.get("direction")),
        _category_similarity(current.get("auction_state"), historical.get("auction_state")),
        _category_similarity(current.get("gamma_regime"), historical.get("gamma_regime")),
        _category_similarity(current.get("vix_regime"), historical.get("vix_regime")),
    ]
    return round(100.0 * (0.65 * sum(numeric) / len(numeric) + 0.35 * sum(categorical) / len(categorical)), 2)


class ExpectancyStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("DB_PATH", "apex_tracking.db")
        self._init()

    def _connect(self):
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def _init(self):
        directory = os.path.dirname(self.db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with self._connect() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS premium_market_fingerprints (
                id INTEGER PRIMARY KEY AUTOINCREMENT, observed_at TEXT NOT NULL,
                session_date TEXT NOT NULL, ticker TEXT NOT NULL, strategy TEXT NOT NULL,
                recommendation_score REAL, fingerprint_json TEXT NOT NULL,
                outcome TEXT, pnl REAL, outcome_source TEXT, graded_at TEXT,
                UNIQUE(session_date, ticker, strategy, fingerprint_json)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_pmf_regime ON premium_market_fingerprints(session_date, ticker, strategy)")
            c.commit()

    def record(self, *, ticker: str, strategy: str, score: float, fingerprint: Dict[str, Any]) -> Dict[str, Any]:
        payload = json.dumps(fingerprint, sort_keys=True, separators=(",", ":"))
        with self._connect() as c:
            c.execute("""INSERT OR IGNORE INTO premium_market_fingerprints
                (observed_at, session_date, ticker, strategy, recommendation_score, fingerprint_json)
                VALUES (?,?,?,?,?,?)""", (fingerprint["observed_at"], fingerprint["session_date"], ticker, strategy, score, payload))
            c.commit()
            row = c.execute("SELECT id FROM premium_market_fingerprints WHERE session_date=? AND ticker=? AND strategy=? AND fingerprint_json=?",
                            (fingerprint["session_date"], ticker, strategy, payload)).fetchone()
        return {"recorded": True, "id": row["id"] if row else None}

    def grade(self, row_id: int, *, outcome: str, pnl: Optional[float], source: str = "OPERATOR") -> bool:
        with self._connect() as c:
            cur = c.execute("UPDATE premium_market_fingerprints SET outcome=?, pnl=?, outcome_source=?, graded_at=? WHERE id=?",
                            (outcome, pnl, source, datetime.now(timezone.utc).isoformat(), int(row_id)))
            c.commit()
        return cur.rowcount == 1

    def rows(self, ticker: str, limit: int = 2000) -> List[Dict[str, Any]]:
        with self._connect() as c:
            rows = c.execute("SELECT * FROM premium_market_fingerprints WHERE ticker=? ORDER BY id DESC LIMIT ?", (ticker, limit)).fetchall()
        out=[]
        for r in rows:
            d=dict(r); d["fingerprint"] = json.loads(d.pop("fingerprint_json")); out.append(d)
        return out


def _strategy_expectancy(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    graded=[r for r in rows if r.get("pnl") is not None]
    pnls=[_f(r.get("pnl")) for r in graded]
    wins=[p for p in pnls if p > 0]
    losses=[p for p in pnls if p < 0]
    return {
        "sample_size": len(graded),
        "win_rate_pct": round(100*len(wins)/len(pnls),1) if pnls else None,
        "average_pnl": round(sum(pnls)/len(pnls),2) if pnls else None,
        "average_winner": round(sum(wins)/len(wins),2) if wins else None,
        "average_loser": round(sum(losses)/len(losses),2) if losses else None,
        "total_pnl": round(sum(pnls),2) if pnls else None,
    }


def _drift(rows: List[Dict[str, Any]], window: int = 20) -> Dict[str, Any]:
    graded=[r for r in rows if r.get("pnl") is not None]
    if len(graded) < window*2:
        return {"available": False, "reason": f"At least {window*2} graded observations are required.", "sample_size": len(graded)}
    recent=[_f(r["pnl"]) for r in graded[:window]]
    prior=[_f(r["pnl"]) for r in graded[window:window*2]]
    ra, pa=sum(recent)/window, sum(prior)/window
    delta=ra-pa
    return {"available": True, "window": window, "recent_expectancy": round(ra,2), "prior_expectancy": round(pa,2),
            "delta": round(delta,2), "state": "DETERIORATING" if delta < 0 else "IMPROVING" if delta > 0 else "STABLE"}


def build_expectancy_intelligence(last_result: Dict[str, Any], *, store: ExpectancyStore,
                                  ticker: str = "SPX", chain_fetcher=None, now_et=None,
                                  expiration: str = "", threshold=None, weights=None,
                                  persist: bool = True, similar_limit: int = 25) -> Dict[str, Any]:
    ranking = rank_premium_strategies(last_result, chain_fetcher=chain_fetcher, now_et=now_et,
                                      symbol=ticker, expiration=expiration, threshold=threshold, weights=weights)
    fp = build_market_fingerprint(last_result)
    if persist and ranking.get("available"):
        for r in ranking.get("rankings") or []:
            store.record(ticker=ticker, strategy=r["strategy"], score=_f(r.get("institutional_score")), fingerprint=fp)
    historical=store.rows(ticker)
    matches=[]
    for row in historical:
        sim=fingerprint_similarity(fp, row["fingerprint"])
        if sim >= 60:
            matches.append({**row, "similarity_score": sim})
    matches.sort(key=lambda r: r["similarity_score"], reverse=True)
    matches=matches[:max(1,min(similar_limit,100))]

    playbook={}
    for strategy in {r.get("strategy") for r in historical} | {r.get("strategy") for r in ranking.get("rankings", [])}:
        sr=[r for r in historical if r.get("strategy")==strategy and r.get("fingerprint",{}).get("regime")==fp["regime"]]
        playbook[strategy]={"regime": fp["regime"], **_strategy_expectancy(sr), "drift": _drift(sr)}

    top=next((r for r in ranking.get("rankings",[]) if r.get("strategy")==ranking.get("recommendation")), None)
    similar_graded=[m for m in matches if m.get("pnl") is not None]
    historical_conf=min(100.0, len(similar_graded)*5.0)
    confidence={
        "structure": round(_f((top or {}).get("direction_fit")),1),
        "execution": round(_f((top or {}).get("execution_confidence")),1),
        "eligibility": round(_f(((top or {}).get("eligibility") or {}).get("score")),1),
        "historical_similarity": round(historical_conf,1),
        "overall": round(0.30*_f((top or {}).get("institutional_score")) + 0.20*historical_conf + 0.25*_f((top or {}).get("execution_confidence")) + 0.25*_f(((top or {}).get("eligibility") or {}).get("score")),1) if top else 0.0,
    }
    return {
        "version": VERSION, "available": bool(ranking.get("available")), "advisory_only": True,
        "execution_authority": False, "current_fingerprint": fp, "premium_intelligence": ranking,
        "recommendation": ranking.get("recommendation", "NO_TRADE"), "confidence": confidence,
        "similar_sessions": {"count": len(matches), "graded_count": len(similar_graded), "matches": matches},
        "regime_playbook": playbook,
        "data_readiness": "READY" if len(similar_graded)>=20 else "BUILDING_HISTORY",
        "governance_note": "Historical expectancy informs ranking context only and never bypasses Premium Discipline hard blockers.",
    }
