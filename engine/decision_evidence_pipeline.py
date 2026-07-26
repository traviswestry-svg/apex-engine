"""APEX 48.2 — Decision Evidence Pipeline.

Bridges immutable recommendation-ledger captures into the existing feature store
and signal spine. Outcomes are written only from governed terminal ledger events;
this module never invents fills, prices, P/L, or directional results.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from typing import Any, Dict, Iterable, Mapping, Optional

from . import feature_store_db

VERSION = "48.2.0_DECISION_EVIDENCE_PIPELINE"
_DB_PATH = lambda: os.getenv("DB_PATH", "apex_tracking.db")


def _iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _float(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _flatten_scalars(value: Any, prefix: str = "", out: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out = out if out is not None else {}
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            _flatten_scalars(item, name, out)
    elif isinstance(value, (list, tuple)):
        # Lists are retained as bounded counts rather than expanded arbitrary payloads.
        out[f"{prefix}.count" if prefix else "list_count"] = len(value)
    elif isinstance(value, (str, int, float, bool)) or value is None:
        out[prefix or "value"] = value
    return out


def _direction(strategy: str) -> str:
    text = (strategy or "").upper()
    if any(token in text for token in ("CALL", "BULL", "PUT_CREDIT")):
        return "BULLISH"
    if any(token in text for token in ("PUT", "BEAR", "CALL_CREDIT")):
        return "BEARISH"
    return "NEUTRAL"


def _ensure_signal_table(conn: sqlite3.Connection) -> None:
    # Match the canonical signal-spine schema so this bridge can safely initialize
    # an empty database before app.py's own idempotent initializer runs.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS apex_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, signal_id TEXT UNIQUE,
            ticker TEXT NOT NULL, direction TEXT NOT NULL, session_date TEXT NOT NULL,
            created_at TEXT NOT NULL, entry_price REAL, entry_low REAL, entry_high REAL,
            stop REAL, target1 REAL, target2 REAL, risk_points REAL, contract TEXT,
            stage TEXT, pine_confirmed INTEGER DEFAULT 0, ici REAL, flow_score REAL,
            conviction REAL, context_json TEXT, status TEXT DEFAULT 'OPEN',
            mfe REAL DEFAULT 0, mae REAL DEFAULT 0, mfe_r REAL DEFAULT 0,
            mae_r REAL DEFAULT 0, last_price REAL, samples INTEGER DEFAULT 0,
            exit_price REAL, exit_at TEXT, exit_reason TEXT, hold_seconds INTEGER,
            outcome_r REAL, updated_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_spine_open ON apex_signals (ticker, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_spine_date ON apex_signals (session_date)")


def capture_recommendation(capture: Mapping[str, Any]) -> Dict[str, Any]:
    """Persist an immutable feature vector and corresponding signal spine row."""
    feature_store_db.init_db()
    sample_id = str(capture["recommendation_id"])
    decision_time = str(capture.get("captured_at") or _iso())
    snapshot = dict(capture.get("snapshot") or {})
    core = {
        "strategy": capture.get("strategy"),
        "premium_kind": capture.get("premium_kind"),
        "tradeable": bool(capture.get("tradeable")),
        "state": capture.get("state"),
        "raw_confidence": capture.get("raw_confidence"),
        "chain_adjusted_confidence": capture.get("chain_adjusted_confidence"),
        "confirmation_multiplier": capture.get("confirmation_multiplier"),
        "final_live_confidence": capture.get("final_live_confidence"),
        "spot": capture.get("spot"),
        "entry_credit": capture.get("entry_credit"),
        "entry_debit": capture.get("entry_debit"),
        "width": capture.get("width"),
        "max_profit": capture.get("max_profit"),
        "max_loss": capture.get("max_loss"),
        "chain_grade": capture.get("chain_grade"),
        "chain_score": capture.get("chain_score"),
        "execution_confidence": capture.get("execution_confidence"),
        "pricing_basis": capture.get("pricing_basis"),
        "quote_age_max_seconds": capture.get("quote_age_max_seconds"),
        "quote_age_avg_seconds": capture.get("quote_age_avg_seconds"),
        "snapshot": snapshot,
    }
    features = _flatten_scalars(core)
    availability = {key: decision_time for key in features}
    vector = {
        "sample_id": sample_id,
        "session_date": str(capture.get("session_date") or decision_time[:10]),
        "ticker": str(capture.get("ticker") or "SPX"),
        "decision_time": decision_time,
        "features": features,
        "feature_availability": availability,
        "max_feature_lag_seconds": 0.0,
        "feature_count": len(features),
        "schema_version": VERSION,
    }
    feature_created = feature_store_db.write_features(vector)

    signal_created = False
    with sqlite3.connect(_DB_PATH(), timeout=10) as conn:
        _ensure_signal_table(conn)
        cur = conn.execute(
            """INSERT OR IGNORE INTO apex_signals
               (signal_id,ticker,direction,session_date,created_at,entry_price,stage,
                conviction,context_json,status,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (sample_id, vector["ticker"], _direction(str(capture.get("strategy") or "")),
             vector["session_date"], decision_time, _float(capture.get("spot")),
             str(capture.get("state") or "OBSERVED"),
             _float(capture.get("final_live_confidence")),
             json.dumps({"recommendation_id": sample_id, "feature_hash": capture.get("feature_hash"),
                         "strategy": capture.get("strategy"), "source": "recommendation_ledger"},
                        sort_keys=True, default=str),
             "OPEN" if capture.get("tradeable") else "OBSERVED", _iso()),
        )
        signal_created = cur.rowcount > 0
        conn.commit()
    return {"sample_id": sample_id, "feature_created": feature_created,
            "signal_created": signal_created}


def process_terminal_event(recommendation: Mapping[str, Any], event_type: str,
                           payload: Mapping[str, Any], event_at: Optional[str] = None) -> Dict[str, Any]:
    """Create a label only when a governed terminal event supplies an outcome."""
    event = (event_type or "").upper()
    if event not in {"CLOSED", "SETTLED", "GRADED", "INVALIDATED"}:
        return {"label_created": False, "reason": "NON_TERMINAL_EVENT"}
    label = payload.get("outcome_label") or recommendation.get("outcome_label")
    if not label and event != "INVALIDATED":
        return {"label_created": False, "reason": "OUTCOME_NOT_SUPPLIED"}
    sample_id = str(recommendation["recommendation_id"])
    labels = {
        "final_outcome": label or "INVALIDATED",
        "outcome_status": event,
        "realized_pnl": _float(payload.get("realized_pnl", recommendation.get("realized_pnl"))),
        "realized_r": _float(payload.get("realized_r", recommendation.get("realized_r"))),
        "executable": (label or "") != "NOT_EXECUTABLE",
        "notes": payload.get("notes") or recommendation.get("outcome_notes"),
    }
    record = {
        "sample_id": sample_id,
        "session_date": recommendation.get("session_date") or str(recommendation.get("captured_at", ""))[:10],
        "decision_time": recommendation.get("captured_at") or _iso(),
        "settled_at": event_at or _iso(),
        "labels": labels,
        "label_basis": "recommendation_ledger_terminal_event",
        "schema_version": VERSION,
    }
    feature_store_db.init_db()
    label_created = feature_store_db.write_label(record)
    with sqlite3.connect(_DB_PATH(), timeout=10) as conn:
        _ensure_signal_table(conn)
        conn.execute("""UPDATE apex_signals SET status=?, outcome_r=?, exit_at=?, exit_reason=?, updated_at=?
                        WHERE signal_id=?""",
                     (event, labels["realized_r"], record["settled_at"], labels["final_outcome"],
                      _iso(), sample_id))
        conn.commit()
    return {"sample_id": sample_id, "label_created": label_created, "labels": labels}


def backfill(recommendations: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    report = {"examined": 0, "features_created": 0, "signals_created": 0,
              "labels_created": 0, "errors": 0}
    for row in recommendations:
        report["examined"] += 1
        try:
            result = capture_recommendation(row)
            report["features_created"] += int(bool(result["feature_created"]))
            report["signals_created"] += int(bool(result["signal_created"]))
            if row.get("outcome_status"):
                label = process_terminal_event(row, str(row["outcome_status"]), row,
                                               row.get("outcome_at"))
                report["labels_created"] += int(bool(label.get("label_created")))
        except Exception:
            report["errors"] += 1
    return report


def readiness() -> Dict[str, Any]:
    feature_store_db.init_db()
    db = _DB_PATH()
    counts = {"recommendations": 0, "features": 0, "signals": 0, "labels": 0,
              "settled_recommendations": 0}
    with sqlite3.connect(db, timeout=10) as conn:
        for key, table in (("recommendations", "recommendation_ledger"),
                           ("features", "flow_features"), ("signals", "apex_signals"),
                           ("labels", "flow_labels")):
            try:
                counts[key] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            except sqlite3.Error:
                counts[key] = 0
        try:
            counts["settled_recommendations"] = int(conn.execute(
                "SELECT COUNT(*) FROM recommendation_ledger WHERE outcome_status IS NOT NULL").fetchone()[0])
        except sqlite3.Error:
            pass
    stages = [
        {"stage": "RECOMMENDATIONS", "count": counts["recommendations"], "status": "PASS" if counts["recommendations"] else "COLLECTING"},
        {"stage": "FEATURES", "count": counts["features"], "status": "PASS" if counts["features"] >= counts["recommendations"] and counts["recommendations"] else "BACKFILL_NEEDED" if counts["recommendations"] else "WAITING"},
        {"stage": "SIGNALS", "count": counts["signals"], "status": "PASS" if counts["signals"] >= counts["recommendations"] and counts["recommendations"] else "BACKFILL_NEEDED" if counts["recommendations"] else "WAITING"},
        {"stage": "OUTCOMES", "count": counts["settled_recommendations"], "status": "PASS" if counts["settled_recommendations"] else "AWAITING_SETTLEMENT"},
        {"stage": "LABELS", "count": counts["labels"], "status": "PASS" if counts["labels"] >= counts["settled_recommendations"] and counts["settled_recommendations"] else "AWAITING_SETTLEMENT"},
    ]
    operational = counts["recommendations"] == 0 or (counts["features"] >= counts["recommendations"] and counts["signals"] >= counts["recommendations"])
    return {"version": VERSION, "status": "HEALTHY" if operational else "ACCUMULATING",
            "operational": operational, "counts": counts, "stages": stages,
            "guardrails": {"fabricates_outcomes": False, "requires_terminal_economics": True,
                           "changes_trade_decisions": False}}
