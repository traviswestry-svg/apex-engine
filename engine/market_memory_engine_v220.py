"""APEX 22.0 — Market Memory Engine.

Append-only, dormant-safe institutional session memory. Capture is disabled by
default and never influences execution. Similarity results are advisory and use
only data available at or before the stored observation timestamp.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

VERSION = "15.0.0_MARKET_MEMORY_ENGINE"
SCHEMA_VERSION = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def capture_enabled() -> bool:
    return _truthy(os.getenv("APEX_MARKET_MEMORY_CAPTURE_ENABLED", "false"))


def _db_path() -> str:
    return os.getenv("APEX_MARKET_MEMORY_DB", "apex_market_memory.db")


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _nested(source: Mapping[str, Any], *paths: str) -> Any:
    for path in paths:
        cur: Any = source
        ok = True
        for key in path.split("."):
            if not isinstance(cur, Mapping) or key not in cur:
                ok = False
                break
            cur = cur[key]
        if ok and cur not in (None, ""):
            return cur
    return None


def _normalize_text(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or default


def _extract_features(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Extract stable, non-secret, pre-outcome market features."""
    return {
        "ticker": _normalize_text(_nested(snapshot, "ticker", "symbol"), "SPX"),
        "session": _normalize_text(_nested(snapshot, "session", "market_session")),
        "market_regime": _normalize_text(_nested(snapshot, "institutional_decision.regime", "regime", "market_regime")),
        "decision": _normalize_text(_nested(snapshot, "institutional_decision.decision", "decision")),
        "bias": _normalize_text(_nested(snapshot, "institutional_decision.bias", "bias", "direction")),
        "opening_type": _normalize_text(_nested(snapshot, "institutional_market_structure.opening_type", "market_structure.opening_type", "opening_type")),
        "auction_state": _normalize_text(_nested(snapshot, "institutional_market_structure.auction_state", "auction_state")),
        "value_migration": _normalize_text(_nested(snapshot, "institutional_market_structure.value_migration", "value_migration")),
        "poc_migration": _normalize_text(_nested(snapshot, "institutional_market_structure.poc_migration", "poc_migration")),
        "dealer_regime": _normalize_text(_nested(snapshot, "dealer_positioning.regime", "dealer_regime", "gamma_regime")),
        "dealer_bias": _normalize_text(_nested(snapshot, "dealer_positioning.bias", "dealer_bias")),
        "flow_bias": _normalize_text(_nested(snapshot, "options_flow_intelligence.bias", "flow_bias")),
        "overnight_structure": _normalize_text(_nested(snapshot, "institutional_intelligence.overnight_structure.state", "overnight_structure", "overnight_state")),
        "preferred_strategy": _normalize_text(_nested(snapshot, "strategy_intelligence.preferred_structure", "preferred_strategy")),
        "confidence": _safe_float(_nested(snapshot, "institutional_decision.confidence", "confidence")),
        "trend_day_probability": _safe_float(_nested(snapshot, "institutional_probability.trend_day_probability", "trend_day_probability")),
        "range_day_probability": _safe_float(_nested(snapshot, "institutional_probability.range_day_probability", "range_day_probability")),
        "spx": _safe_float(_nested(snapshot, "spx", "price", "underlying_price", "market.spx")),
        "vix": _safe_float(_nested(snapshot, "vix", "market.vix")),
        "poc": _safe_float(_nested(snapshot, "volume_profile.poc", "institutional_market_structure.primary_profile.poc", "poc")),
        "vah": _safe_float(_nested(snapshot, "volume_profile.vah", "institutional_market_structure.primary_profile.vah", "vah")),
        "val": _safe_float(_nested(snapshot, "volume_profile.val", "institutional_market_structure.primary_profile.val", "val")),
        "expected_move": _safe_float(_nested(snapshot, "institutional_probability.expected_move_points", "expected_move", "expected_move_points")),
    }


def _sanitize_snapshot(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Persist a bounded allow-list only; never raw provider or credential payloads."""
    features = _extract_features(snapshot)
    return {
        "features": features,
        "source_versions": {
            "application": _normalize_text(_nested(snapshot, "version", "application_version"), "UNKNOWN"),
            "decision": _normalize_text(_nested(snapshot, "institutional_decision.version"), "UNKNOWN"),
        },
        "data_fresh": bool(snapshot.get("data_fresh", False)),
        "is_tradeable": bool(snapshot.get("is_tradeable", False)),
    }


def _connect(path: Optional[str] = None) -> sqlite3.Connection:
    resolved = path or _db_path()
    parent = Path(resolved).expanduser().resolve().parent
    parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_store(path: Optional[str] = None) -> None:
    with _connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS market_memory_sessions (
                memory_id TEXT PRIMARY KEY,
                observed_at TEXT NOT NULL,
                session_date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                session TEXT NOT NULL,
                feature_hash TEXT NOT NULL,
                features_json TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                outcome_json TEXT,
                outcome_status TEXT NOT NULL DEFAULT 'PENDING',
                created_at TEXT NOT NULL,
                schema_version INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_market_memory_date ON market_memory_sessions(session_date DESC);
            CREATE INDEX IF NOT EXISTS idx_market_memory_ticker ON market_memory_sessions(ticker, observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_market_memory_outcome ON market_memory_sessions(outcome_status);
            """
        )


def capture_snapshot(snapshot: Mapping[str, Any], *, observed_at: Optional[str] = None,
                     path: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    if not force and not capture_enabled():
        return {"ok": False, "state": "LOCKED", "captured": False,
                "reason": "APEX_MARKET_MEMORY_CAPTURE_ENABLED is false", "version": VERSION}
    safe = _sanitize_snapshot(snapshot if isinstance(snapshot, Mapping) else {})
    features = safe["features"]
    timestamp = observed_at or _utc_now()
    session_date = timestamp[:10]
    serialized = json.dumps(features, sort_keys=True, separators=(",", ":"))
    feature_hash = hashlib.sha256(serialized.encode()).hexdigest()
    memory_id = hashlib.sha256(f"{timestamp}|{features['ticker']}|{feature_hash}".encode()).hexdigest()[:24]
    initialize_store(path)
    with _connect(path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO market_memory_sessions
            (memory_id, observed_at, session_date, ticker, session, feature_hash,
             features_json, snapshot_json, created_at, schema_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (memory_id, timestamp, session_date, features["ticker"], features["session"],
             feature_hash, serialized, json.dumps(safe, sort_keys=True), _utc_now(), SCHEMA_VERSION),
        )
        inserted = conn.total_changes > 0
    return {"ok": True, "state": "CAPTURED" if inserted else "DUPLICATE", "captured": inserted,
            "memory_id": memory_id, "observed_at": timestamp, "feature_hash": feature_hash,
            "version": VERSION, "guardrails": _guardrails()}


def attach_outcome(memory_id: str, outcome: Mapping[str, Any], *, path: Optional[str] = None,
                   force: bool = False) -> Dict[str, Any]:
    if not force and not _truthy(os.getenv("APEX_MARKET_MEMORY_OUTCOME_WRITES_ENABLED", "false")):
        return {"ok": False, "state": "LOCKED", "updated": False,
                "reason": "Outcome writes are disabled", "version": VERSION}
    allowed = {k: outcome.get(k) for k in ("result", "max_favorable_excursion", "max_adverse_excursion",
                                           "close_location", "new_daily_high", "new_daily_low") if k in outcome}
    initialize_store(path)
    with _connect(path) as conn:
        cur = conn.execute("UPDATE market_memory_sessions SET outcome_json=?, outcome_status='GRADED' WHERE memory_id=?",
                           (json.dumps(allowed, sort_keys=True), memory_id))
    return {"ok": cur.rowcount == 1, "updated": cur.rowcount == 1, "memory_id": memory_id,
            "state": "GRADED" if cur.rowcount == 1 else "NOT_FOUND", "version": VERSION}


def _similarity(a: Mapping[str, Any], b: Mapping[str, Any]) -> Tuple[float, List[str]]:
    categorical = ["market_regime", "bias", "opening_type", "auction_state", "value_migration",
                   "poc_migration", "dealer_regime", "dealer_bias", "flow_bias", "overnight_structure"]
    numeric = [("confidence", 100.0), ("trend_day_probability", 100.0),
               ("range_day_probability", 100.0), ("vix", 20.0)]
    score = 0.0
    weight = 0.0
    matches: List[str] = []
    for key in categorical:
        av, bv = a.get(key), b.get(key)
        if av in (None, "UNKNOWN") or bv in (None, "UNKNOWN"):
            continue
        weight += 1.0
        if av == bv:
            score += 1.0
            matches.append(key)
    for key, scale in numeric:
        av, bv = _safe_float(a.get(key)), _safe_float(b.get(key))
        if av is None or bv is None:
            continue
        weight += 0.75
        score += 0.75 * max(0.0, 1.0 - abs(av - bv) / scale)
    return (round(100.0 * score / weight, 1) if weight else 0.0, matches)


def find_similar(current: Mapping[str, Any], *, limit: int = 10, min_score: float = 55.0,
                 path: Optional[str] = None, before: Optional[str] = None) -> Dict[str, Any]:
    features = _extract_features(current if isinstance(current, Mapping) else {})
    initialize_store(path)
    sql = "SELECT * FROM market_memory_sessions"
    params: List[Any] = []
    if before:
        sql += " WHERE observed_at < ?"
        params.append(before)
    sql += " ORDER BY observed_at DESC LIMIT 2000"
    with _connect(path) as conn:
        rows = conn.execute(sql, params).fetchall()
    ranked = []
    for row in rows:
        candidate = json.loads(row["features_json"])
        score, matches = _similarity(features, candidate)
        if score < min_score:
            continue
        ranked.append({"memory_id": row["memory_id"], "observed_at": row["observed_at"],
                       "session_date": row["session_date"], "ticker": row["ticker"],
                       "similarity": score, "matched_features": matches,
                       "features": candidate, "outcome_status": row["outcome_status"],
                       "outcome": json.loads(row["outcome_json"]) if row["outcome_json"] else None})
    ranked.sort(key=lambda x: (x["similarity"], x["observed_at"]), reverse=True)
    return {"ok": True, "version": VERSION, "count": min(len(ranked), max(1, min(limit, 50))),
            "matches": ranked[:max(1, min(limit, 50))], "look_ahead_protected": bool(before),
            "guardrails": _guardrails()}


def list_sessions(*, limit: int = 50, path: Optional[str] = None) -> Dict[str, Any]:
    initialize_store(path)
    with _connect(path) as conn:
        rows = conn.execute("SELECT memory_id, observed_at, session_date, ticker, session, features_json, outcome_status FROM market_memory_sessions ORDER BY observed_at DESC LIMIT ?",
                            (max(1, min(limit, 250)),)).fetchall()
    return {"ok": True, "version": VERSION, "count": len(rows),
            "sessions": [{**dict(r), "features": json.loads(r["features_json"])} for r in rows],
            "guardrails": _guardrails()}


def status(path: Optional[str] = None) -> Dict[str, Any]:
    try:
        initialize_store(path)
        with _connect(path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM market_memory_sessions").fetchone()[0]
            graded = conn.execute("SELECT COUNT(*) FROM market_memory_sessions WHERE outcome_status='GRADED'").fetchone()[0]
            first = conn.execute("SELECT MIN(observed_at) FROM market_memory_sessions").fetchone()[0]
            latest = conn.execute("SELECT MAX(observed_at) FROM market_memory_sessions").fetchone()[0]
        min_ready = max(1, int(os.getenv("APEX_MARKET_MEMORY_MIN_SESSIONS", "20")))
        return {"ok": True, "version": VERSION, "state": "READY" if total >= min_ready else "DORMANT",
                "capture_enabled": capture_enabled(), "outcome_writes_enabled": _truthy(os.getenv("APEX_MARKET_MEMORY_OUTCOME_WRITES_ENABLED", "false")),
                "sessions": total, "graded_sessions": graded, "minimum_sessions_for_learning": min_ready,
                "learning_ready": total >= min_ready and graded >= max(5, min_ready // 2),
                "first_observation": first, "latest_observation": latest, "database_configured": bool(_db_path()),
                "evaluated_at": _utc_now(), "guardrails": _guardrails()}
    except Exception as exc:
        return {"ok": False, "version": VERSION, "state": "WARNING", "capture_enabled": capture_enabled(),
                "sessions": 0, "graded_sessions": 0, "learning_ready": False,
                "error": type(exc).__name__, "evaluated_at": _utc_now(), "guardrails": _guardrails()}


def diagnostics(path: Optional[str] = None) -> Dict[str, Any]:
    s = status(path)
    s["schema_version"] = SCHEMA_VERSION
    s["storage"] = {"type": "sqlite", "path_configured": bool(_db_path()), "append_only_capture": True,
                    "raw_provider_payloads_persisted": False, "secrets_persisted": False}
    s["capabilities"] = ["session_memory", "feature_index", "similarity_search", "outcome_attachment", "look_ahead_protection"]
    s["dormant_reasons"] = [] if s.get("learning_ready") else ["Insufficient captured and graded sessions"]
    return s


def _guardrails() -> Dict[str, Any]:
    return {"changes_trade_decisions": False, "execution_advisory_only": True, "broker_mutation": False,
            "automatic_execution": False, "human_confirmation_required": True,
            "capture_disabled_by_default": True, "secrets_persisted": False,
            "look_ahead_protection": True}
