"""APEX 15.1: Institutional Market State Engine (IMSE).

Deterministic, decision-time market-state classification. IMSE records immutable
state snapshots and transitions without mutating recommendations, confidence,
risk, execution, champion selection, or governance.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import uuid
from typing import Any

from . import institutional_governance as gov

VERSION = "15.0.15.1"
SCHEMA_VERSION = "apex.imse.v1"
TAXONOMY = (
    "BALANCED_AUCTION", "TREND_AUCTION", "DOUBLE_DISTRIBUTION", "FAILED_AUCTION",
    "GAMMA_PIN", "GAMMA_EXPANSION", "GAMMA_TRANSITION",
    "LOW_VOLATILITY_COMPRESSION", "HIGH_VOLATILITY_EXPANSION",
    "INSTITUTIONAL_ACCUMULATION", "INSTITUTIONAL_DISTRIBUTION", "THIN_LIQUIDITY",
)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _json(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), default=str)


def _load(v: Any, default: Any = None) -> Any:
    if v in (None, ""): return {} if default is None else default
    try: return json.loads(v)
    except Exception: return {} if default is None else default


def _conn():
    c = sqlite3.connect(gov.DB_PATH); c.row_factory = sqlite3.Row; c.execute("PRAGMA foreign_keys=ON"); return c


def init_db() -> dict[str, Any]:
    gov.init_db()
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS institutional_market_states(
          market_state_id TEXT PRIMARY KEY,
          symbol TEXT NOT NULL,
          session_id TEXT NOT NULL,
          observed_at TEXT NOT NULL,
          active_state TEXT NOT NULL,
          active_confidence REAL NOT NULL,
          stability_index REAL NOT NULL,
          secondary_states_json TEXT NOT NULL,
          scores_json TEXT NOT NULL,
          drivers_json TEXT NOT NULL,
          source_snapshot_json TEXT NOT NULL,
          schema_version TEXT NOT NULL,
          engine_version TEXT NOT NULL,
          integrity_hash TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(symbol, session_id, observed_at)
        );
        CREATE INDEX IF NOT EXISTS idx_imse_symbol_time ON institutional_market_states(symbol, observed_at);
        CREATE TABLE IF NOT EXISTS institutional_market_state_transitions(
          transition_id TEXT PRIMARY KEY,
          symbol TEXT NOT NULL,
          session_id TEXT NOT NULL,
          from_state TEXT,
          to_state TEXT NOT NULL,
          transition_at TEXT NOT NULL,
          prior_market_state_id TEXT,
          market_state_id TEXT NOT NULL,
          confidence_delta REAL NOT NULL,
          integrity_hash TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(symbol, session_id, market_state_id)
        );
        CREATE INDEX IF NOT EXISTS idx_imse_transition_time ON institutional_market_state_transitions(symbol, transition_at);
        """)
    return {"ok": True, "schema_version": SCHEMA_VERSION, "build_version": VERSION}


def _num(d: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for k in keys:
        v = d.get(k)
        try:
            if v is not None: return float(v)
        except Exception: pass
    return default


def _flag(d: dict[str, Any], *keys: str) -> bool:
    for k in keys:
        v = d.get(k)
        if isinstance(v, bool): return v
        if str(v).upper() in {"TRUE","YES","ON","RISING","POSITIVE","BULLISH","EXPANDING"}: return True
    return False


def classify(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Classify only the supplied snapshot; no database or future data access."""
    s = dict(snapshot or {})
    atr_pct = _num(s, "atr_pct", "atr_percent", "volatility_pct")
    trend = abs(_num(s, "trend_strength", "adx", "directional_strength"))
    balance = _num(s, "balance_score", "auction_balance", default=50)
    gamma = _num(s, "gamma_score", "net_gamma", "gex")
    gamma_distance = abs(_num(s, "gamma_flip_distance_pct", "gamma_distance_pct", default=9))
    breadth = _num(s, "breadth", "breadth_score", "advance_decline")
    flow = _num(s, "flow_bias", "institutional_flow", "premium_bias")
    liquidity = _num(s, "liquidity_score", "depth_score", default=70)
    value_break = _flag(s, "value_break", "accepted_outside_value")
    failed = _flag(s, "failed_auction", "failed_breakout")
    double = _flag(s, "double_distribution")

    scores = {k: 0.0 for k in TAXONOMY}
    scores["BALANCED_AUCTION"] = max(0, min(100, balance + max(0, 20-trend) - (15 if value_break else 0)))
    scores["TREND_AUCTION"] = max(0, min(100, trend + (25 if value_break else 0) + min(20, abs(breadth)/5)))
    scores["DOUBLE_DISTRIBUTION"] = 90 if double else max(0, min(65, trend + atr_pct*8 - balance/3))
    scores["FAILED_AUCTION"] = 92 if failed else max(0, min(60, (25 if value_break else 0) + max(0, 30-trend)))
    scores["GAMMA_PIN"] = max(0, min(100, 85 - gamma_distance*12 + (10 if gamma > 0 else 0)))
    scores["GAMMA_EXPANSION"] = max(0, min(100, abs(gamma)/10 + atr_pct*12 + (15 if gamma < 0 else 0)))
    scores["GAMMA_TRANSITION"] = max(0, min(100, 80 - gamma_distance*15 + atr_pct*5))
    scores["LOW_VOLATILITY_COMPRESSION"] = max(0, min(100, 90 - atr_pct*20 + balance/5))
    scores["HIGH_VOLATILITY_EXPANSION"] = max(0, min(100, atr_pct*25 + trend/2))
    scores["INSTITUTIONAL_ACCUMULATION"] = max(0, min(100, max(0, flow)*0.7 + max(0, breadth)*0.3))
    scores["INSTITUTIONAL_DISTRIBUTION"] = max(0, min(100, max(0, -flow)*0.7 + max(0, -breadth)*0.3))
    scores["THIN_LIQUIDITY"] = max(0, min(100, 100-liquidity + atr_pct*5))
    scores = {k: round(v, 2) for k, v in scores.items()}
    ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    active, confidence = ranked[0]
    secondary = [{"state": k, "confidence": v} for k, v in ranked[1:4] if v >= 35]
    margin = confidence - ranked[1][1]
    agreement = max(0, 100 - abs(scores["TREND_AUCTION"] - scores["HIGH_VOLATILITY_EXPANSION"])/2)
    stability = round(max(0, min(100, 45 + margin*0.8 + agreement*0.25 - atr_pct*2)), 2)
    drivers = {
        "atr_pct": atr_pct, "trend_strength": trend, "balance_score": balance,
        "gamma_score": gamma, "gamma_flip_distance_pct": gamma_distance,
        "breadth": breadth, "flow_bias": flow, "liquidity_score": liquidity,
        "value_break": value_break, "failed_auction": failed, "double_distribution": double,
    }
    return {"active_state": active, "active_confidence": confidence, "stability_index": stability,
            "secondary_states": secondary, "scores": scores, "drivers": drivers,
            "taxonomy": list(TAXONOMY), "future_information_used": False}


def record(snapshot: dict[str, Any], *, symbol: str = "SPX", session_id: str = "", observed_at: str | None = None, actor: str = "SYSTEM") -> dict[str, Any]:
    init_db(); observed_at = observed_at or str(snapshot.get("observed_at") or _now()); session_id = session_id or str(snapshot.get("session_id") or observed_at[:10])
    result = classify(snapshot)
    with _conn() as c:
        existing = c.execute("SELECT * FROM institutional_market_states WHERE symbol=? AND session_id=? AND observed_at=?", (symbol, session_id, observed_at)).fetchone()
    if existing:
        return {"ok": True, "status": "IMMUTABLE_EXISTS", "created": False, **_row(existing), "production_effect": "NONE"}
    payload = {"symbol": symbol, "session_id": session_id, "observed_at": observed_at, **result,
               "source_snapshot": snapshot, "schema_version": SCHEMA_VERSION, "engine_version": VERSION}
    ih = hashlib.sha256(_json(payload).encode()).hexdigest(); msid = str(uuid.uuid4()); created = _now()
    with _conn() as c:
        c.execute("INSERT INTO institutional_market_states VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            msid, symbol, session_id, observed_at, result["active_state"], result["active_confidence"], result["stability_index"],
            _json(result["secondary_states"]), _json(result["scores"]), _json(result["drivers"]), _json(snapshot),
            SCHEMA_VERSION, VERSION, ih, created))
        prior = c.execute("SELECT * FROM institutional_market_states WHERE symbol=? AND session_id=? AND market_state_id<>? AND observed_at<=? ORDER BY observed_at DESC LIMIT 1", (symbol, session_id, msid, observed_at)).fetchone()
        if prior is None or prior["active_state"] != result["active_state"]:
            tpay = {"symbol": symbol, "session_id": session_id, "from_state": prior["active_state"] if prior else None,
                    "to_state": result["active_state"], "transition_at": observed_at, "prior_market_state_id": prior["market_state_id"] if prior else None,
                    "market_state_id": msid, "confidence_delta": round(result["active_confidence"] - (prior["active_confidence"] if prior else 0), 2)}
            tih = hashlib.sha256(_json(tpay).encode()).hexdigest()
            c.execute("INSERT INTO institutional_market_state_transitions VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                str(uuid.uuid4()), symbol, session_id, tpay["from_state"], tpay["to_state"], observed_at, tpay["prior_market_state_id"], msid, tpay["confidence_delta"], tih, created))
    gov.audit("RECORD_MARKET_STATE", "institutional_market_state", msid, new={"active_state":result["active_state"],"integrity_hash":ih}, actor=actor, explanation="Immutable decision-time market state recorded")
    return {"ok": True, "status": "CREATED", "created": True, "market_state_id": msid, **payload, "integrity_hash": ih, "created_at": created, "production_effect": "NONE"}


def _row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    d = dict(row)
    for k in ("secondary_states_json","scores_json","drivers_json","source_snapshot_json"):
        if k in d: d[k[:-5]] = _load(d.pop(k), [] if k=="secondary_states_json" else {})
    return d


def at_or_before(observed_at: str, symbol: str = "SPX") -> dict[str, Any]:
    init_db()
    with _conn() as c:
        row = c.execute("SELECT * FROM institutional_market_states WHERE symbol=? AND observed_at<=? ORDER BY observed_at DESC LIMIT 1", (symbol, observed_at)).fetchone()
    return {"ok": False, "status": "UNAVAILABLE"} if not row else {"ok": True, "status": "READY", **_row(row), "future_information_allowed": False, "production_effect": "NONE"}


def current(symbol: str = "SPX") -> dict[str, Any]:
    init_db()
    with _conn() as c: row = c.execute("SELECT * FROM institutional_market_states WHERE symbol=? ORDER BY observed_at DESC LIMIT 1", (symbol,)).fetchone()
    return {"ok": False, "status": "UNAVAILABLE"} if not row else {"ok": True, "status": "READY", **_row(row), "future_information_allowed": False, "production_effect": "NONE"}


def history(symbol: str = "SPX", limit: int = 100) -> list[dict[str, Any]]:
    init_db()
    with _conn() as c: rows = c.execute("SELECT * FROM institutional_market_states WHERE symbol=? ORDER BY observed_at DESC LIMIT ?", (symbol, max(1,min(int(limit),1000)))).fetchall()
    return [_row(r) for r in rows]


def transitions(symbol: str = "SPX", limit: int = 100) -> list[dict[str, Any]]:
    init_db()
    with _conn() as c: rows = c.execute("SELECT * FROM institutional_market_state_transitions WHERE symbol=? ORDER BY transition_at DESC LIMIT ?", (symbol,max(1,min(int(limit),1000)))).fetchall()
    return [dict(r) for r in rows]


def dashboard(symbol: str = "SPX") -> dict[str, Any]:
    cur = current(symbol)
    return {"ok": True, "status": "READY", "current": cur if cur.get("ok") else None,
            "history": history(symbol, 50), "transitions": transitions(symbol, 50), "taxonomy": list(TAXONOMY),
            "schema_version": SCHEMA_VERSION, "build_version": VERSION, "future_information_allowed": False, "production_effect": "NONE"}


def status() -> dict[str, Any]:
    init_db()
    with _conn() as c:
        states = c.execute("SELECT COUNT(*) FROM institutional_market_states").fetchone()[0]
        trans = c.execute("SELECT COUNT(*) FROM institutional_market_state_transitions").fetchone()[0]
    return {"status": "READY", "schema_version": SCHEMA_VERSION, "build_version": VERSION, "taxonomy": list(TAXONOMY),
            "state_count": states, "transition_count": trans, "deterministic": True, "future_information_allowed": False,
            "recommendation_mutation_enabled": False, "confidence_mutation_enabled": False, "production_effect": "NONE"}
