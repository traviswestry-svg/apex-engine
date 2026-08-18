"""APEX 66.3.2 stateful institutional thesis lifecycle.

Persistence/governance only. This module does not synthesize market direction,
consensus, conviction, or trade actions. It persists the canonical thesis
candidate produced by institutional_narrative and applies deterministic,
machine-evaluable lifecycle transitions.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import threading

from .canonical_persistence import connect as canonical_connect
from typing import Any, Dict, List, Mapping, Optional, Tuple

VERSION = "66.3.2"
SCHEMA_VERSION = "apex.institutional_thesis.v2"
_LOCK = threading.RLock()
TERMINAL_STATES = {"INVALIDATED", "EXPIRED", "CLOSED"}
VALID_STATES = {"FORMING", "ACTIVE", "WEAKENING", "CONFLICTED", "INVALIDATED", "EXPIRED", "CLOSED", "UNKNOWN"}


def _db_path() -> str:
    return os.getenv("RECOMMENDATION_LEDGER_DB_PATH") or os.getenv("DB_PATH", "apex_tracking.db")


def _connect() -> sqlite3.Connection:
    # APEX 67.6: thesis state is decision-adjacent canonical state. Preserve the
    # existing DB path/schema/timeout while delegating connection policy to the
    # canonical persistence layer.
    return canonical_connect(_db_path(), timeout=10)


def _iso(value: Optional[dt.datetime] = None) -> str:
    return (value or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _num(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def init_db() -> None:
    """Additive persistence; never rewrites recommendation history."""
    with _LOCK, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS institutional_thesis_state (
                thesis_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                session_date TEXT NOT NULL,
                state TEXT NOT NULL,
                dominant_direction TEXT NOT NULL,
                current_thesis TEXT NOT NULL,
                alternative_thesis TEXT,
                market_regime TEXT,
                raw_conviction REAL,
                calibrated_conviction REAL,
                effective_consensus REAL,
                hard_invalidation_json TEXT NOT NULL,
                soft_invalidation_json TEXT NOT NULL,
                supporting_engines_json TEXT NOT NULL,
                contradicting_engines_json TEXT NOT NULL,
                abstaining_engines_json TEXT NOT NULL,
                known_unknowns_json TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                snapshot_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                invalidated_at TEXT,
                closed_at TEXT,
                revision INTEGER NOT NULL DEFAULT 1,
                UNIQUE(ticker, session_date)
            );
            CREATE INDEX IF NOT EXISTS idx_its_ticker_session
                ON institutional_thesis_state(ticker, session_date);
            CREATE INDEX IF NOT EXISTS idx_its_state
                ON institutional_thesis_state(state);
            CREATE TABLE IF NOT EXISTS institutional_thesis_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thesis_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                session_date TEXT NOT NULL,
                event_type TEXT NOT NULL,
                from_state TEXT,
                to_state TEXT NOT NULL,
                event_at TEXT NOT NULL,
                reason TEXT,
                payload_json TEXT NOT NULL,
                FOREIGN KEY(thesis_id) REFERENCES institutional_thesis_state(thesis_id)
            );
            CREATE INDEX IF NOT EXISTS idx_ite_thesis
                ON institutional_thesis_events(thesis_id, event_at);
            """
        )
        conn.commit()


def _loads(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _decode_state(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    for field in (
        "hard_invalidation_json", "soft_invalidation_json", "supporting_engines_json",
        "contradicting_engines_json", "abstaining_engines_json", "known_unknowns_json", "provenance_json",
    ):
        key = field[:-5]
        default = [] if key != "provenance" else {}
        d[key] = _loads(d.pop(field, None), default)
    return d


def get_state(ticker: str, session_date: str) -> Optional[Dict[str, Any]]:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM institutional_thesis_state WHERE ticker=? AND session_date=?",
            (ticker.upper(), session_date),
        ).fetchone()
        return _decode_state(row) if row else None


def get_events(thesis_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT event_type,from_state,to_state,event_at,reason,payload_json "
            "FROM institutional_thesis_events WHERE thesis_id=? ORDER BY id DESC LIMIT ?",
            (thesis_id, max(1, min(int(limit), 1000))),
        ).fetchall()
    out = []
    for row in reversed(rows):
        item = dict(row)
        item["payload"] = _loads(item.pop("payload_json", None), {})
        out.append(item)
    return out


def _trigger_value(trigger: Mapping[str, Any]) -> Optional[float]:
    for key in ("level", "value", "price", "threshold"):
        n = _num(trigger.get(key))
        if n is not None:
            return n
    return None


def evaluate_trigger(trigger: Mapping[str, Any], *, price: Optional[float], previous_price: Optional[float] = None) -> Tuple[bool, str]:
    """Evaluate only explicit operators. Unknown/ambiguous operators fail closed (not triggered)."""
    if not isinstance(trigger, Mapping):
        return False, "INVALID_TRIGGER"
    if trigger.get("machine_evaluable") is False:
        return False, "NOT_MACHINE_EVALUABLE"
    op = str(trigger.get("operator") or "").strip().upper()
    level = _trigger_value(trigger)
    if price is None or level is None or not op:
        return False, "INSUFFICIENT_TRIGGER_DATA"
    hit = False
    if op in {"LT", "BELOW"}: hit = price < level
    elif op in {"LTE", "AT_OR_BELOW"}: hit = price <= level
    elif op in {"GT", "ABOVE"}: hit = price > level
    elif op in {"GTE", "AT_OR_ABOVE"}: hit = price >= level
    elif op == "CROSSES_BELOW" and previous_price is not None: hit = previous_price >= level and price < level
    elif op == "CROSSES_ABOVE" and previous_price is not None: hit = previous_price <= level and price > level
    else:
        return False, "UNSUPPORTED_OPERATOR"
    return bool(hit), "TRIGGERED" if hit else "NOT_TRIGGERED"


def evaluate_invalidations(thesis: Mapping[str, Any], *, price: Optional[float], previous_price: Optional[float] = None) -> Dict[str, Any]:
    hard_hits, soft_hits = [], []
    for severity, key, bucket in (("HARD", "hard_invalidation", hard_hits), ("SOFT", "soft_invalidation", soft_hits)):
        for trigger in thesis.get(key) or []:
            hit, result = evaluate_trigger(trigger, price=price, previous_price=previous_price)
            if hit:
                row = dict(trigger)
                row.update({"severity": severity, "evaluation": result, "observed_price": price})
                bucket.append(row)
    return {"hard_triggered": bool(hard_hits), "soft_triggered": bool(soft_hits), "hard_hits": hard_hits, "soft_hits": soft_hits}


def _derive_state(candidate: Mapping[str, Any], prior: Optional[Mapping[str, Any]], invalidation: Mapping[str, Any], *, market_closed: bool) -> Tuple[str, str]:
    requested = str(candidate.get("state") or "UNKNOWN").upper()
    direction = str(candidate.get("dominant_direction") or "UNKNOWN").upper()
    raw = _num(candidate.get("raw_conviction")) or 0.0
    consensus = _num(candidate.get("consensus")) or 0.0

    if invalidation.get("hard_triggered"):
        return "INVALIDATED", "HARD_INVALIDATION_TRIGGERED"

    if market_closed:
        # Do not create a terminal CLOSED record for a session that never had a live thesis.
        if prior and str(prior.get("state") or "").upper() not in TERMINAL_STATES:
            return "CLOSED", "MARKET_SESSION_CLOSED"
        return requested if requested in VALID_STATES else "UNKNOWN", "MARKET_CLOSED_NO_ACTIVE_PRIOR"

    if not prior:
        return requested if requested in VALID_STATES else "UNKNOWN", "INITIAL_THESIS"

    prior_state = str(prior.get("state") or "UNKNOWN").upper()
    prior_dir = str(prior.get("dominant_direction") or "UNKNOWN").upper()
    prior_raw = _num(prior.get("raw_conviction")) or 0.0
    prior_consensus = _num(prior.get("effective_consensus")) or 0.0

    if prior_state == "INVALIDATED":
        if direction in {"BULLISH", "BEARISH"} and direction != prior_dir and requested in {"FORMING", "ACTIVE"}:
            return "FORMING", "REPLACEMENT_AFTER_INVALIDATION"
        return "INVALIDATED", "PRESERVE_HARD_INVALIDATION"
    if prior_state in {"CLOSED", "EXPIRED"}:
        return requested if requested in VALID_STATES else "UNKNOWN", "NEW_LIFECYCLE_AFTER_TERMINAL"
    if requested == "CONFLICTED":
        return "CONFLICTED", "CURRENT_EVIDENCE_CONFLICTED"
    if invalidation.get("soft_triggered"):
        return "WEAKENING", "SOFT_INVALIDATION_TRIGGERED"
    if direction in {"BULLISH", "BEARISH"} and prior_dir in {"BULLISH", "BEARISH"} and direction != prior_dir:
        return "CONFLICTED", "DIRECTIONAL_REVERSAL_BEFORE_INVALIDATION"
    # Explicit strengthening/weaking based only on already computed canonical metrics.
    if requested == "ACTIVE" and raw >= prior_raw + 5 and consensus >= prior_consensus:
        return "ACTIVE", "THESIS_STRENGTHENED"
    if prior_state == "ACTIVE" and (raw <= max(0.0, prior_raw - 10) or consensus <= max(0.0, prior_consensus - 15)):
        return "WEAKENING", "THESIS_EVIDENCE_WEAKENED"
    if requested == "ACTIVE":
        return "ACTIVE", "ACTIVE_EVIDENCE_MAINTAINED"
    if requested == "FORMING" and prior_state == "WEAKENING" and raw > prior_raw and consensus > prior_consensus:
        return "FORMING", "THESIS_RECOVERING"
    return requested if requested in VALID_STATES else "UNKNOWN", "CANDIDATE_STATE_APPLIED"


def _snapshot_hash(candidate: Mapping[str, Any]) -> str:
    material = {
        "current_thesis": candidate.get("current_thesis"),
        "alternative_thesis": candidate.get("alternative_thesis"),
        "dominant_direction": candidate.get("dominant_direction"),
        "market_regime": candidate.get("market_regime"),
        "consensus": candidate.get("consensus"),
        "raw_conviction": candidate.get("raw_conviction"),
        "calibrated_conviction": candidate.get("calibrated_conviction"),
        "hard_invalidation": candidate.get("hard_invalidation") or [],
        "soft_invalidation": candidate.get("soft_invalidation") or [],
        "supporting_engines": candidate.get("supporting_engines") or [],
        "contradicting_engines": candidate.get("contradicting_engines") or [],
        "abstaining_engines": candidate.get("abstaining_engines") or [],
        "known_unknowns": candidate.get("known_unknowns") or [],
    }
    return hashlib.sha256(_json(material).encode("utf-8")).hexdigest()



def expire_prior_sessions(ticker: str, current_session_date: str, *, event_at: Optional[str] = None) -> int:
    """Expire older nonterminal theses when a newer session begins."""
    init_db(); ticker=ticker.upper(); at=event_at or _iso(); count=0
    with _LOCK, _connect() as conn:
        rows=conn.execute(
            "SELECT thesis_id,session_date,state,revision FROM institutional_thesis_state WHERE ticker=? AND session_date<? AND state NOT IN ('INVALIDATED','EXPIRED','CLOSED')",
            (ticker,current_session_date),
        ).fetchall()
        for row in rows:
            rev=int(row['revision'] or 0)+1
            conn.execute("UPDATE institutional_thesis_state SET state='EXPIRED',updated_at=?,closed_at=?,revision=? WHERE thesis_id=?",(at,at,rev,row['thesis_id']))
            conn.execute(
                "INSERT INTO institutional_thesis_events(thesis_id,ticker,session_date,event_type,from_state,to_state,event_at,reason,payload_json) VALUES(?,?,?,?,?,?,?,?,?)",
                (row['thesis_id'],ticker,row['session_date'],'THESIS_EXPIRED',row['state'],'EXPIRED',at,'NEWER_SESSION_STARTED',_json({'revision':rev,'new_session_date':current_session_date})),
            )
            count+=1
        conn.commit()
    return count

def persist_thesis(candidate: Mapping[str, Any], *, ticker: str, session_date: str,
                   price: Optional[float], market_closed: bool = False,
                   generated_at: Optional[str] = None) -> Dict[str, Any]:
    """Persist/evolve one canonical thesis. No direction or conviction synthesis occurs here."""
    init_db()
    ticker = ticker.upper()
    at = generated_at or _iso()
    if not market_closed:
        expire_prior_sessions(ticker, session_date, event_at=at)
    prior = get_state(ticker, session_date)
    previous_price = None
    if prior:
        previous_price = _num((prior.get("provenance") or {}).get("last_price"))
    invalidation = evaluate_invalidations(candidate, price=price, previous_price=previous_price)
    if market_closed and not prior:
        out = dict(candidate)
        out["schema_version"] = SCHEMA_VERSION
        out["lifecycle"] = {"schema_version":"apex.thesis_lifecycle.v1","version":VERSION,"state":str(candidate.get("state") or "UNKNOWN"),"transition_reason":"MARKET_CLOSED_NO_ACTIVE_PRIOR","invalidation_evaluation":invalidation,"revision":0,"persisted":False}
        out["events"] = []
        return out
    next_state, reason = _derive_state(candidate, prior, invalidation, market_closed=market_closed)
    thesis_id = prior.get("thesis_id") if prior else str(__import__("uuid").uuid5(__import__("uuid").NAMESPACE_URL, f"apex-thesis:{ticker}:{session_date}"))
    snapshot_hash = _snapshot_hash(candidate)
    prior_revision = int(prior.get("revision") or 0) if prior else 0
    material_change = (not prior) or next_state != (prior.get("state") if prior else None) or snapshot_hash != (prior.get("snapshot_hash") if prior else None)
    revision = prior_revision + 1 if material_change else max(1, prior_revision)
    provenance = dict(candidate.get("provenance") or {})
    provenance.update({"lifecycle_manager":"thesis_lifecycle","lifecycle_version":VERSION,"last_price":price})
    event_type = "THESIS_CREATED" if not prior else "THESIS_STATE_CHANGED" if next_state != prior.get("state") else "THESIS_UPDATED"
    if next_state == "INVALIDATED": event_type = "THESIS_INVALIDATED"
    elif next_state == "CLOSED": event_type = "THESIS_CLOSED"
    elif reason == "THESIS_STRENGTHENED": event_type = "THESIS_STRENGTHENED"
    elif next_state == "WEAKENING": event_type = "THESIS_WEAKENED"
    elif reason == "REPLACEMENT_AFTER_INVALIDATION": event_type = "THESIS_REPLACED"

    with _LOCK, _connect() as conn:
        now = _iso()
        if prior and not material_change:
            conn.execute("UPDATE institutional_thesis_state SET provenance_json=?,updated_at=? WHERE thesis_id=?", (_json(provenance), now, thesis_id))
            conn.commit()
            current = get_state(ticker, session_date) or {}
            current["events"] = get_events(thesis_id)
            current["lifecycle"] = {"schema_version":"apex.thesis_lifecycle.v1","version":VERSION,"state":next_state,"transition_reason":"NO_MATERIAL_CHANGE","invalidation_evaluation":invalidation,"revision":revision,"persisted":True}
            return current
        if prior:
            conn.execute(
                """UPDATE institutional_thesis_state SET state=?,dominant_direction=?,current_thesis=?,alternative_thesis=?,
                market_regime=?,raw_conviction=?,calibrated_conviction=?,effective_consensus=?,hard_invalidation_json=?,
                soft_invalidation_json=?,supporting_engines_json=?,contradicting_engines_json=?,abstaining_engines_json=?,
                known_unknowns_json=?,provenance_json=?,snapshot_hash=?,updated_at=?,invalidated_at=?,closed_at=?,revision=?
                WHERE thesis_id=?""",
                (
                    next_state, str(candidate.get("dominant_direction") or "UNKNOWN"), str(candidate.get("current_thesis") or "NO_LIVE_THESIS"),
                    candidate.get("alternative_thesis"), candidate.get("market_regime"), _num(candidate.get("raw_conviction")),
                    _num(candidate.get("calibrated_conviction")), _num(candidate.get("consensus")), _json(candidate.get("hard_invalidation") or []),
                    _json(candidate.get("soft_invalidation") or []), _json(candidate.get("supporting_engines") or []),
                    _json(candidate.get("contradicting_engines") or []), _json(candidate.get("abstaining_engines") or []),
                    _json(candidate.get("known_unknowns") or []), _json(provenance), snapshot_hash, now,
                    at if next_state == "INVALIDATED" else prior.get("invalidated_at"),
                    at if next_state == "CLOSED" else prior.get("closed_at"), revision, thesis_id,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO institutional_thesis_state(thesis_id,ticker,session_date,state,dominant_direction,current_thesis,
                alternative_thesis,market_regime,raw_conviction,calibrated_conviction,effective_consensus,hard_invalidation_json,
                soft_invalidation_json,supporting_engines_json,contradicting_engines_json,abstaining_engines_json,known_unknowns_json,
                provenance_json,snapshot_hash,created_at,updated_at,invalidated_at,closed_at,revision)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    thesis_id,ticker,session_date,next_state,str(candidate.get("dominant_direction") or "UNKNOWN"),
                    str(candidate.get("current_thesis") or "NO_LIVE_THESIS"),candidate.get("alternative_thesis"),candidate.get("market_regime"),
                    _num(candidate.get("raw_conviction")),_num(candidate.get("calibrated_conviction")),_num(candidate.get("consensus")),
                    _json(candidate.get("hard_invalidation") or []),_json(candidate.get("soft_invalidation") or []),
                    _json(candidate.get("supporting_engines") or []),_json(candidate.get("contradicting_engines") or []),
                    _json(candidate.get("abstaining_engines") or []),_json(candidate.get("known_unknowns") or []),_json(provenance),snapshot_hash,
                    now,now,at if next_state=="INVALIDATED" else None,at if next_state=="CLOSED" else None,revision,
                ),
            )
        payload = {
            "reason": reason, "candidate_state": candidate.get("state"), "direction": candidate.get("dominant_direction"),
            "raw_conviction": candidate.get("raw_conviction"), "consensus": candidate.get("consensus"),
            "invalidation_evaluation": invalidation, "snapshot_hash": snapshot_hash, "revision": revision,
        }
        # Avoid noisy duplicate update events when the canonical snapshot is unchanged and state is unchanged.
        if material_change:
            conn.execute(
                "INSERT INTO institutional_thesis_events(thesis_id,ticker,session_date,event_type,from_state,to_state,event_at,reason,payload_json) VALUES(?,?,?,?,?,?,?,?,?)",
                (thesis_id,ticker,session_date,event_type,prior.get("state") if prior else None,next_state,at,reason,_json(payload)),
            )
        conn.commit()

    current = get_state(ticker, session_date) or {}
    current["events"] = get_events(thesis_id)
    current["lifecycle"] = {
        "schema_version": "apex.thesis_lifecycle.v1", "version": VERSION, "state": next_state, "transition_reason": reason,
        "invalidation_evaluation": invalidation, "revision": revision, "persisted": True,
    }
    return current
