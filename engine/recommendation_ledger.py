"""APEX 11.0E durable recommendation memory.

Captures immutable decision-time recommendation economics and provenance before
history-dependent analytics are allowed to make claims.  The ledger is append-
only for recommendations; lifecycle changes are stored as events and explicit
outcome fields rather than rewriting the original decision snapshot.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import threading
import uuid
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

VERSION = "11.0E_RECOMMENDATION_LEDGER"
SCHEMA_VERSION = 1
_LOCK = threading.RLock()
_REQUIRED_CAPTURE_FIELDS = (
    "recommendation_id", "captured_at", "session_date", "ticker", "strategy",
    "raw_confidence", "final_live_confidence", "legs_json", "snapshot_json",
    "feature_hash", "ledger_schema_version", "application_version",
)
_TERMINAL_STATES = {"CLOSED", "SETTLED", "INVALIDATED", "GRADED"}


def _db_path() -> str:
    return os.getenv("RECOMMENDATION_LEDGER_DB_PATH") or os.getenv("DB_PATH", "apex_tracking.db")


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(value: Optional[dt.datetime] = None) -> str:
    return (value or _utcnow()).astimezone(dt.timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _connect() -> sqlite3.Connection:
    path = _db_path()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _LOCK, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS recommendation_ledger (
                recommendation_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                captured_at TEXT NOT NULL,
                session_date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                strategy TEXT NOT NULL,
                premium_kind TEXT,
                state TEXT NOT NULL DEFAULT 'OBSERVED',
                tradeable INTEGER NOT NULL DEFAULT 0,
                raw_confidence REAL,
                chain_adjusted_confidence REAL,
                confirmation_multiplier REAL,
                final_live_confidence REAL,
                calibrated_confidence REAL,
                spot REAL,
                expiration TEXT,
                entry_credit REAL,
                entry_debit REAL,
                width REAL,
                max_profit REAL,
                max_loss REAL,
                chain_grade TEXT,
                chain_score REAL,
                execution_confidence REAL,
                pricing_basis TEXT,
                quote_age_max_seconds REAL,
                quote_age_avg_seconds REAL,
                legs_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                probability_json TEXT NOT NULL,
                confirmation_json TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                feature_hash TEXT NOT NULL,
                ledger_schema_version INTEGER NOT NULL,
                application_version TEXT NOT NULL,
                build TEXT,
                commit_sha TEXT,
                decision_engine_version TEXT,
                pricing_engine_version TEXT,
                chain_quality_version TEXT,
                source TEXT NOT NULL DEFAULT 'premium_strategy',
                outcome_status TEXT,
                outcome_label TEXT,
                realized_pnl REAL,
                realized_r REAL,
                outcome_notes TEXT,
                outcome_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_rl_session ON recommendation_ledger(session_date, ticker);
            CREATE INDEX IF NOT EXISTS idx_rl_state ON recommendation_ledger(state);
            CREATE INDEX IF NOT EXISTS idx_rl_outcome ON recommendation_ledger(outcome_status);
            CREATE TABLE IF NOT EXISTS recommendation_ledger_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recommendation_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                FOREIGN KEY(recommendation_id) REFERENCES recommendation_ledger(recommendation_id)
            );
            CREATE INDEX IF NOT EXISTS idx_rle_rec ON recommendation_ledger_events(recommendation_id, event_at);
            """
        )
        conn.commit()


def _quote_age_stats(chain_legs: Sequence[Mapping[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
    ages = [_safe_float(row.get("quote_age_seconds")) for row in chain_legs]
    ages = [x for x in ages if x is not None and x >= 0]
    if not ages:
        return None, None
    return max(ages), sum(ages) / len(ages)


def _extract_probability(last_result: Mapping[str, Any], panel: Mapping[str, Any]) -> Any:
    return (panel.get("probability_distribution") or last_result.get("probability_distribution")
            or last_result.get("scenario_distribution") or {})


def _extract_confirmation(last_result: Mapping[str, Any], panel: Mapping[str, Any]) -> Any:
    return (panel.get("confirmation") or last_result.get("confirmation_scan")
            or last_result.get("confirmation") or {})


def _extract_evidence(last_result: Mapping[str, Any], panel: Mapping[str, Any]) -> Any:
    return (panel.get("evidence") or last_result.get("evidence_graph")
            or last_result.get("evidence") or last_result.get("decision_trace") or {})


def _confidence_fields(panel: Mapping[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    raw = _safe_float(panel.get("raw_confidence"))
    final = _safe_float(panel.get("final_live_confidence"))
    displayed = _safe_float(panel.get("confidence"))
    chain = _safe_float(panel.get("chain_adjusted_confidence"))
    multiplier = _safe_float(panel.get("confirmation_multiplier"))
    if raw is None:
        raw = displayed
    if chain is None:
        chain = displayed
    if final is None:
        final = displayed
    return raw, chain, multiplier, final


def build_capture(
    *, ticker: str, panel: Mapping[str, Any], last_result: Optional[Mapping[str, Any]] = None,
    session_date: Optional[str] = None, spot: Optional[float] = None,
    application_version: Optional[str] = None, build: Optional[str] = None,
    commit_sha: Optional[str] = None, captured_at: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    """Create a deterministic decision-time snapshot without persisting it."""
    lr = dict(last_result or {})
    p = dict(panel or {})
    legs = dict(p.get("legs") or {})
    chain_legs = list(legs.get("chain_legs") or [])
    quality = dict(legs.get("chain_quality") or p.get("chain_quality") or {})
    now = captured_at or _utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    sess = session_date or now.date().isoformat()
    raw, chain_adj, confirmation_mult, final = _confidence_fields(p)
    qmax, qavg = _quote_age_stats(chain_legs)
    strategy = str(p.get("strategy") or "NO_TRADE")
    expiration = str(p.get("expiration") or legs.get("expiration") or lr.get("expiration") or sess)[:10]

    # Hash only point-in-time inputs, never outcomes or mutable lifecycle fields.
    feature_snapshot = {
        "ticker": ticker.upper(), "session_date": sess, "strategy": strategy,
        "spot": _safe_float(spot) if spot is not None else _safe_float(p.get("spot") or ((lr.get("market_state") or {}).get("price"))),
        "legs": legs, "evidence": _extract_evidence(lr, p),
        "probability": _extract_probability(lr, p),
        "confirmation": _extract_confirmation(lr, p),
        "market_state": lr.get("market_state") or {},
        "institutional_state": lr.get("institutional_state") or {},
    }
    feature_hash = hashlib.sha256(_json(feature_snapshot).encode("utf-8")).hexdigest()
    decision_epoch = now.replace(second=0, microsecond=0).isoformat()
    material = {
        "session_date": sess, "ticker": ticker.upper(), "strategy": strategy,
        "expiration": expiration, "legs": legs, "decision_epoch": decision_epoch,
    }
    idem = hashlib.sha256(_json(material).encode("utf-8")).hexdigest()
    recommendation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"apex:{idem}"))

    return {
        "recommendation_id": recommendation_id,
        "idempotency_key": idem,
        "captured_at": now.astimezone(dt.timezone.utc).isoformat(),
        "session_date": sess,
        "ticker": ticker.upper(),
        "strategy": strategy,
        "premium_kind": p.get("premium_kind"),
        "state": "ACTIONABLE" if p.get("tradeable") and strategy != "NO_TRADE" else "OBSERVED",
        "tradeable": bool(p.get("tradeable")),
        "raw_confidence": raw,
        "chain_adjusted_confidence": chain_adj,
        "confirmation_multiplier": confirmation_mult,
        "final_live_confidence": final,
        "spot": feature_snapshot["spot"],
        "expiration": expiration,
        "entry_credit": _safe_float(legs.get("entry_credit")),
        "entry_debit": _safe_float(legs.get("entry_debit")),
        "width": _safe_float(legs.get("width")),
        "max_profit": _safe_float(legs.get("max_profit")),
        "max_loss": _safe_float(legs.get("max_loss")),
        "chain_grade": legs.get("chain_grade") or quality.get("grade"),
        "chain_score": _safe_float(quality.get("score")),
        "execution_confidence": _safe_float(legs.get("execution_confidence") or quality.get("execution_confidence")),
        "pricing_basis": legs.get("pricing_basis"),
        "quote_age_max_seconds": qmax,
        "quote_age_avg_seconds": qavg,
        "legs": legs,
        "evidence": feature_snapshot["evidence"],
        "probability": feature_snapshot["probability"],
        "confirmation": feature_snapshot["confirmation"],
        "snapshot": feature_snapshot,
        "feature_hash": feature_hash,
        "ledger_schema_version": SCHEMA_VERSION,
        "application_version": application_version or os.getenv("APEX_VERSION", "unknown"),
        "build": build or os.getenv("RENDER_GIT_COMMIT", "")[:12] or os.getenv("APEX_BUILD"),
        "commit_sha": commit_sha or os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT"),
        "decision_engine_version": p.get("decision_engine_version") or lr.get("decision_engine_version"),
        "pricing_engine_version": p.get("pricing_engine_version") or "premium_chain_pricing",
        "chain_quality_version": p.get("chain_quality_version") or quality.get("version"),
        "source": "premium_strategy",
    }


def record_recommendation(capture: Mapping[str, Any]) -> Dict[str, Any]:
    """Persist exactly one immutable capture. Duplicate idempotency keys return the original row."""
    init_db()
    now = _iso()
    with _LOCK, _connect() as conn:
        existing = conn.execute(
            "SELECT recommendation_id FROM recommendation_ledger WHERE idempotency_key=?",
            (capture["idempotency_key"],),
        ).fetchone()
        if existing:
            return {"created": False, "recommendation_id": existing["recommendation_id"], "duplicate": True}
        conn.execute(
            """INSERT INTO recommendation_ledger (
                recommendation_id,idempotency_key,captured_at,session_date,ticker,strategy,premium_kind,state,tradeable,
                raw_confidence,chain_adjusted_confidence,confirmation_multiplier,final_live_confidence,
                spot,expiration,entry_credit,entry_debit,width,max_profit,max_loss,chain_grade,chain_score,
                execution_confidence,pricing_basis,quote_age_max_seconds,quote_age_avg_seconds,
                legs_json,evidence_json,probability_json,confirmation_json,snapshot_json,feature_hash,
                ledger_schema_version,application_version,build,commit_sha,decision_engine_version,
                pricing_engine_version,chain_quality_version,source,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                capture["recommendation_id"], capture["idempotency_key"], capture["captured_at"], capture["session_date"],
                capture["ticker"], capture["strategy"], capture.get("premium_kind"), capture.get("state", "OBSERVED"),
                1 if capture.get("tradeable") else 0, capture.get("raw_confidence"), capture.get("chain_adjusted_confidence"),
                capture.get("confirmation_multiplier"), capture.get("final_live_confidence"), capture.get("spot"),
                capture.get("expiration"), capture.get("entry_credit"), capture.get("entry_debit"), capture.get("width"),
                capture.get("max_profit"), capture.get("max_loss"), capture.get("chain_grade"), capture.get("chain_score"),
                capture.get("execution_confidence"), capture.get("pricing_basis"), capture.get("quote_age_max_seconds"),
                capture.get("quote_age_avg_seconds"), _json(capture.get("legs") or {}), _json(capture.get("evidence") or {}),
                _json(capture.get("probability") or {}), _json(capture.get("confirmation") or {}),
                _json(capture.get("snapshot") or {}), capture["feature_hash"], capture.get("ledger_schema_version", SCHEMA_VERSION),
                capture.get("application_version", "unknown"), capture.get("build"), capture.get("commit_sha"),
                capture.get("decision_engine_version"), capture.get("pricing_engine_version"), capture.get("chain_quality_version"),
                capture.get("source", "premium_strategy"), now, now,
            ),
        )
        conn.execute(
            "INSERT INTO recommendation_ledger_events(recommendation_id,event_type,event_at,payload_json) VALUES(?,?,?,?)",
            (capture["recommendation_id"], "CAPTURED", capture["captured_at"], _json({"state": capture.get("state")})),
        )
        conn.commit()
    return {"created": True, "recommendation_id": capture["recommendation_id"], "duplicate": False}


def append_event(recommendation_id: str, event_type: str, payload: Optional[Mapping[str, Any]] = None,
                 event_at: Optional[str] = None) -> Dict[str, Any]:
    init_db()
    event = event_type.strip().upper().replace("-", "_")
    allowed = {"ACTIVATED", "QUOTE_SNAPSHOT", "FILL", "CLOSED", "SETTLED", "INVALIDATED", "GRADED",
               "STATE_CHANGE", "NARRATIVE_SNAPSHOT", "CONSENSUS_SNAPSHOT", "CONVICTION_SNAPSHOT",
               "EXECUTION_SNAPSHOT", "POSITION_QUALITY_SNAPSHOT", "RISK_CHANGE", "INVALIDATION_CHANGE",
               "MARKET_PROGRESS"}
    if event not in allowed:
        raise ValueError(f"unsupported event_type: {event_type}")
    at = event_at or _iso()
    data = dict(payload or {})
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT state FROM recommendation_ledger WHERE recommendation_id=?", (recommendation_id,)).fetchone()
        if not row:
            raise KeyError(recommendation_id)
        conn.execute(
            "INSERT INTO recommendation_ledger_events(recommendation_id,event_type,event_at,payload_json) VALUES(?,?,?,?)",
            (recommendation_id, event, at, _json(data)),
        )
        updates = ["updated_at=?"]
        args: List[Any] = [_iso()]
        if event not in {"QUOTE_SNAPSHOT", "NARRATIVE_SNAPSHOT", "CONSENSUS_SNAPSHOT", "CONVICTION_SNAPSHOT", "EXECUTION_SNAPSHOT", "POSITION_QUALITY_SNAPSHOT", "RISK_CHANGE", "INVALIDATION_CHANGE", "MARKET_PROGRESS"}:
            updates.append("state=?")
            args.append(event)
        if event in {"CLOSED", "SETTLED", "INVALIDATED", "GRADED"}:
            updates.extend(["outcome_status=?", "outcome_label=?", "realized_pnl=?", "realized_r=?", "outcome_notes=?", "outcome_at=?"])
            args.extend([event, data.get("outcome_label"), _safe_float(data.get("realized_pnl")),
                         _safe_float(data.get("realized_r")), data.get("notes"), at])
        args.append(recommendation_id)
        conn.execute(f"UPDATE recommendation_ledger SET {', '.join(updates)} WHERE recommendation_id=?", args)
        conn.commit()
    return {"ok": True, "recommendation_id": recommendation_id, "event_type": event, "event_at": at}


def _decode_row(row: sqlite3.Row) -> Dict[str, Any]:
    out = dict(row)
    for key in ("legs_json", "evidence_json", "probability_json", "confirmation_json", "snapshot_json"):
        raw = out.pop(key, None)
        out[key[:-5]] = json.loads(raw) if raw else {}
    out["tradeable"] = bool(out.get("tradeable"))
    return out


def get_recommendation(recommendation_id: str) -> Optional[Dict[str, Any]]:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM recommendation_ledger WHERE recommendation_id=?", (recommendation_id,)).fetchone()
        if not row:
            return None
        out = _decode_row(row)
        events = conn.execute("SELECT event_type,event_at,payload_json FROM recommendation_ledger_events WHERE recommendation_id=? ORDER BY id", (recommendation_id,)).fetchall()
        out["events"] = [{"event_type": e["event_type"], "event_at": e["event_at"], "payload": json.loads(e["payload_json"] or "{}") } for e in events]
        return out


def list_recommendations(*, limit: int = 100, session_date: Optional[str] = None,
                         strategy: Optional[str] = None, state: Optional[str] = None,
                         unresolved_only: bool = False) -> List[Dict[str, Any]]:
    init_db()
    clauses, args = [], []
    if session_date:
        clauses.append("session_date=?"); args.append(session_date)
    if strategy:
        clauses.append("strategy=?"); args.append(strategy)
    if state:
        clauses.append("state=?"); args.append(state)
    if unresolved_only:
        clauses.append("outcome_status IS NULL")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with _connect() as conn:
        rows = conn.execute(f"SELECT * FROM recommendation_ledger{where} ORDER BY captured_at DESC LIMIT ?", (*args, max(1, min(limit, 500)))).fetchall()
    return [_decode_row(r) for r in rows]


def counts() -> Dict[str, Any]:
    init_db()
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) n FROM recommendation_ledger").fetchone()["n"]
        today = _utcnow().date().isoformat()
        captured_today = conn.execute("SELECT COUNT(*) n FROM recommendation_ledger WHERE session_date=?", (today,)).fetchone()["n"]
        unresolved = conn.execute("SELECT COUNT(*) n FROM recommendation_ledger WHERE outcome_status IS NULL").fetchone()["n"]
        by_state = {r["state"]: r["n"] for r in conn.execute("SELECT state,COUNT(*) n FROM recommendation_ledger GROUP BY state")}
        by_strategy = {r["strategy"]: r["n"] for r in conn.execute("SELECT strategy,COUNT(*) n FROM recommendation_ledger GROUP BY strategy")}
    return {"total": total, "captured_today": captured_today, "unresolved": unresolved,
            "gradeable": max(0, total - unresolved), "by_state": by_state, "by_strategy": by_strategy}


def coverage() -> Dict[str, Any]:
    init_db()
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) n FROM recommendation_ledger").fetchone()["n"]
        field_counts: Dict[str, int] = {}
        if total:
            for field in _REQUIRED_CAPTURE_FIELDS:
                field_counts[field] = conn.execute(f"SELECT COUNT(*) n FROM recommendation_ledger WHERE {field} IS NOT NULL AND CAST({field} AS TEXT) != ''").fetchone()["n"]
    if not total:
        return {"status": "COLLECTING", "total": 0, "coverage_pct": None, "required_fields": list(_REQUIRED_CAPTURE_FIELDS), "fields": {}}
    fields = {k: {"present": n, "missing": total - n, "coverage_pct": round(n * 100 / total, 2)} for k, n in field_counts.items()}
    pct = round(sum(field_counts.values()) * 100 / (total * len(_REQUIRED_CAPTURE_FIELDS)), 2)
    return {"status": "PASS" if pct == 100 else "WARN", "total": total, "coverage_pct": pct, "fields": fields}


def health() -> Dict[str, Any]:
    started = _utcnow()
    try:
        init_db()
        with _connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("ROLLBACK")
            last = conn.execute("SELECT captured_at FROM recommendation_ledger ORDER BY captured_at DESC LIMIT 1").fetchone()
            total = conn.execute("SELECT COUNT(*) n FROM recommendation_ledger").fetchone()["n"]
        return {"status": "PASS", "writable": True, "db_path": _db_path(), "schema_version": SCHEMA_VERSION,
                "total": total, "last_capture_at": last["captured_at"] if last else None,
                "duration_ms": round((_utcnow() - started).total_seconds() * 1000, 2)}
    except Exception as exc:
        return {"status": "FAIL", "writable": False, "db_path": _db_path(), "error": str(exc)}


def calibration_readiness(minimum: int = 50) -> Dict[str, Any]:
    c = counts()
    gradeable = int(c["gradeable"])
    return {"status": "READY" if gradeable >= minimum else "INSUFFICIENT_HISTORY",
            "gradeable_rows": gradeable, "minimum_required": minimum,
            "remaining": max(0, minimum - gradeable), "calibration_enabled": gradeable >= minimum}
