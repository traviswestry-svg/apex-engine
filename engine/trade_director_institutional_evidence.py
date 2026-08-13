"""APEX Trade Director Phase 31 — Institutional Evidence & Outcome Validation.

Creates immutable point-in-time decision snapshots and grades them from supplied
SPX bars. This module measures the existing system; it does not mutate engine
weights, authorize trades, place orders, or fabricate outcomes.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

VERSION = "PHASE_31"
ACTIONABLE_STATES = {"ARMED", "EXECUTE", "ENTER", "AUTHORIZED"}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS apex_evidence_decisions (
 decision_id TEXT PRIMARY KEY, trade_id TEXT, symbol TEXT NOT NULL, decision_time TEXT NOT NULL,
 decision_state TEXT NOT NULL, direction TEXT NOT NULL, confidence REAL NOT NULL,
 entry_price REAL, stop_price REAL, target_price REAL, horizon_minutes INTEGER NOT NULL,
 feature_vector_json TEXT NOT NULL, engine_attribution_json TEXT NOT NULL,
 source_snapshot_json TEXT NOT NULL, lineage_id TEXT, snapshot_hash TEXT NOT NULL,
 created_at TEXT NOT NULL, graded INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS apex_evidence_outcomes (
 outcome_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL UNIQUE, graded_at TEXT NOT NULL,
 grade TEXT NOT NULL, exit_reason TEXT NOT NULL, exit_time TEXT, exit_price REAL,
 mfe_points REAL NOT NULL, mae_points REAL NOT NULL, realized_points REAL NOT NULL,
 target_hit INTEGER NOT NULL, stop_hit INTEGER NOT NULL, bars_evaluated INTEGER NOT NULL,
 grading_method TEXT NOT NULL, outcome_json TEXT NOT NULL, outcome_hash TEXT NOT NULL,
 FOREIGN KEY(decision_id) REFERENCES apex_evidence_decisions(decision_id)
);
CREATE TABLE IF NOT EXISTS apex_evidence_events (
 event_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL, event_type TEXT NOT NULL,
 occurred_at TEXT NOT NULL, payload_json TEXT NOT NULL, previous_hash TEXT,
 integrity_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_decision_time ON apex_evidence_decisions(decision_time DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_decision_grade ON apex_evidence_decisions(graded, decision_time);
CREATE INDEX IF NOT EXISTS idx_evidence_outcome_grade ON apex_evidence_outcomes(grade, graded_at DESC);
CREATE TRIGGER IF NOT EXISTS apex_evidence_decisions_no_update BEFORE UPDATE ON apex_evidence_decisions
BEGIN SELECT RAISE(ABORT, 'decision snapshots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS apex_evidence_decisions_no_delete BEFORE DELETE ON apex_evidence_decisions
BEGIN SELECT RAISE(ABORT, 'decision snapshots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS apex_evidence_outcomes_no_update BEFORE UPDATE ON apex_evidence_outcomes
BEGIN SELECT RAISE(ABORT, 'graded outcomes are immutable'); END;
CREATE TRIGGER IF NOT EXISTS apex_evidence_outcomes_no_delete BEFORE DELETE ON apex_evidence_outcomes
BEGIN SELECT RAISE(ABORT, 'graded outcomes are immutable'); END;
CREATE TRIGGER IF NOT EXISTS apex_evidence_events_no_update BEFORE UPDATE ON apex_evidence_events
BEGIN SELECT RAISE(ABORT, 'evidence events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS apex_evidence_events_no_delete BEFORE DELETE ON apex_evidence_events
BEGIN SELECT RAISE(ABORT, 'evidence events are immutable'); END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def evidence_db_path() -> str:
    configured = os.getenv("APEX_EVIDENCE_DB", "").strip()
    if configured:
        return configured
    if os.path.isdir("/data") and os.access("/data", os.W_OK):
        return "/data/apex_evidence.db"
    return os.path.join(os.getcwd(), "apex_evidence.db")


def _connect() -> sqlite3.Connection:
    path = evidence_db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


def initialize_evidence_store() -> str:
    with _connect():
        pass
    return evidence_db_path()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    text = value if isinstance(value, str) else _canonical(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _m(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _parse_json(value: str, default: Any) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return default


def _decision(row: sqlite3.Row) -> Dict[str, Any]:
    item = dict(row)
    item["feature_vector"] = _parse_json(item.pop("feature_vector_json"), {})
    item["engine_attribution"] = _parse_json(item.pop("engine_attribution_json"), {})
    item["source_snapshot"] = _parse_json(item.pop("source_snapshot_json"), {})
    item["graded"] = bool(item["graded"])
    return item


def _outcome(row: sqlite3.Row) -> Dict[str, Any]:
    item = dict(row)
    item["outcome"] = _parse_json(item.pop("outcome_json"), {})
    item["target_hit"] = bool(item["target_hit"])
    item["stop_hit"] = bool(item["stop_hit"])
    return item


def _record_event(conn: sqlite3.Connection, decision_id: str, event_type: str, payload: Mapping[str, Any]) -> None:
    previous = conn.execute(
        "SELECT integrity_hash FROM apex_evidence_events WHERE decision_id=? ORDER BY occurred_at DESC,rowid DESC LIMIT 1",
        (decision_id,),
    ).fetchone()
    event = {"event_id": str(uuid.uuid4()), "decision_id": decision_id, "event_type": event_type,
             "occurred_at": _now(), "payload": dict(payload), "previous_hash": previous[0] if previous else ""}
    integrity_hash = _hash(event)
    conn.execute("INSERT INTO apex_evidence_events VALUES (?,?,?,?,?,?,?)",
                 (event["event_id"], decision_id, event_type, event["occurred_at"],
                  _canonical(event["payload"]), event["previous_hash"], integrity_hash))


def _extract(context: Mapping[str, Any]) -> Dict[str, Any]:
    decision = _m(context.get("institutional_decision_engine"))
    authorization = _m(context.get("authorization") or decision.get("authorization"))
    lifecycle = _m(context.get("trade_lifecycle"))
    command = _m(context.get("institutional_command_center"))
    recommendation = _m(context.get("recommendation"))
    levels = _m(context.get("levels") or context.get("key_levels"))
    state = str(_first(authorization.get("state"), authorization.get("authorization_state"),
                       lifecycle.get("state"), decision.get("decision"), recommendation.get("action"),
                       context.get("decision_state"), "OBSERVE")).upper()
    direction = str(_first(decision.get("direction"), recommendation.get("direction"),
                           context.get("direction"), context.get("side"), "NONE")).upper()
    confidence = _f(_first(decision.get("confidence"), decision.get("final_score"),
                           recommendation.get("confidence"), context.get("confidence"),
                           _m(command.get("system_confidence_index")).get("score")))
    entry = _f(_first(context.get("entry_price"), recommendation.get("entry"), levels.get("entry"), context.get("price")))
    stop = _f(_first(context.get("stop_price"), recommendation.get("stop"), levels.get("stop")))
    target = _f(_first(context.get("target_price"), recommendation.get("target"), levels.get("target")))
    attribution = _m(decision.get("confidence_attribution") or context.get("confidence_attribution"))
    feature_vector = dict(_m(context.get("feature_vector")))
    if not feature_vector:
        for key in ("gamma_regime", "flow_intelligence", "auction", "market_regime", "multi_timeframe_intelligence",
                    "options_intelligence", "portfolio_allocation", "execution_certification"):
            if key in context:
                feature_vector[key] = context.get(key)
    return {
        "trade_id": str(_first(context.get("trade_id"), lifecycle.get("trade_id"), authorization.get("trade_id"), "")),
        "symbol": str(context.get("symbol") or context.get("ticker") or "SPX").upper(),
        "decision_time": str(_first(context.get("checked_at"), context.get("timestamp"), _now())),
        "decision_state": state, "direction": direction, "confidence": confidence,
        "entry_price": entry or None, "stop_price": stop or None, "target_price": target or None,
        "horizon_minutes": max(1, int(_f(context.get("evidence_horizon_minutes"), 30))),
        "feature_vector": feature_vector, "engine_attribution": dict(attribution),
        "lineage_id": str(_m(context.get("data_lineage")).get("lineage_id") or ""),
    }


def capture_decision(context: Mapping[str, Any], *, force: bool = False) -> Dict[str, Any]:
    """Persist one immutable point-in-time snapshot; duplicates are idempotent."""
    extracted = _extract(context)
    if not force and extracted["decision_state"] not in ACTIONABLE_STATES:
        return {"ok": False, "captured": False, "state": "NOT_ACTIONABLE", "decision_state": extracted["decision_state"]}
    if extracted["direction"] not in {"CALL", "PUT", "LONG", "SHORT", "BULLISH", "BEARISH"}:
        return {"ok": False, "captured": False, "state": "INVALID_DIRECTION"}
    source_snapshot = json.loads(_canonical(context))
    identity = {k: extracted[k] for k in ("trade_id", "symbol", "decision_time", "decision_state", "direction")}
    identity["source_hash"] = _hash(source_snapshot)
    decision_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "apex-evidence:" + _hash(identity)))
    snapshot_hash = _hash({"decision_id": decision_id, **extracted, "source_snapshot": source_snapshot})
    created_at = _now()
    with _connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO apex_evidence_decisions
            (decision_id,trade_id,symbol,decision_time,decision_state,direction,confidence,entry_price,stop_price,target_price,
             horizon_minutes,feature_vector_json,engine_attribution_json,source_snapshot_json,lineage_id,snapshot_hash,created_at,graded)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
            (decision_id, extracted["trade_id"], extracted["symbol"], extracted["decision_time"], extracted["decision_state"],
             extracted["direction"], extracted["confidence"], extracted["entry_price"], extracted["stop_price"],
             extracted["target_price"], extracted["horizon_minutes"], _canonical(extracted["feature_vector"]),
             _canonical(extracted["engine_attribution"]), _canonical(source_snapshot), extracted["lineage_id"],
             snapshot_hash, created_at),
        )
        row = conn.execute("SELECT * FROM apex_evidence_decisions WHERE decision_id=?", (decision_id,)).fetchone()
        events = conn.execute("SELECT COUNT(*) c FROM apex_evidence_events WHERE decision_id=?", (decision_id,)).fetchone()["c"]
        if not events:
            _record_event(conn, decision_id, "DECISION_CAPTURED", {"snapshot_hash": snapshot_hash})
    return {"ok": True, "captured": True, "duplicate": row["created_at"] != created_at, "decision": _decision(row)}


def get_decision(decision_id: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM apex_evidence_decisions WHERE decision_id=?", (decision_id,)).fetchone()
        if not row:
            return None
        result = _decision(row)
        out = conn.execute("SELECT * FROM apex_evidence_outcomes WHERE decision_id=?", (decision_id,)).fetchone()
        result["outcome"] = _outcome(out) if out else None
        events = conn.execute("SELECT * FROM apex_evidence_events WHERE decision_id=? ORDER BY occurred_at", (decision_id,)).fetchall()
        result["events"] = [dict(e) for e in events]
        return result


def list_decisions(limit: int = 100, graded: Optional[bool] = None) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 100), 1000))
    with _connect() as conn:
        if graded is None:
            rows = conn.execute("SELECT * FROM apex_evidence_decisions ORDER BY decision_time DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM apex_evidence_decisions WHERE graded=? ORDER BY decision_time DESC LIMIT ?", (int(graded), limit)).fetchall()
    return [_decision(r) for r in rows]


def _normalize_bars(bars: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    normalized = []
    for bar in bars:
        ts = str(_first(bar.get("timestamp"), bar.get("time"), bar.get("t"), ""))
        if not ts:
            continue
        normalized.append({"timestamp": ts, "open": _f(bar.get("open", bar.get("o"))),
                           "high": _f(bar.get("high", bar.get("h"))), "low": _f(bar.get("low", bar.get("l"))),
                           "close": _f(bar.get("close", bar.get("c")))})
    return sorted(normalized, key=lambda b: b["timestamp"])


def grade_decision(decision_id: str, bars: Sequence[Mapping[str, Any]], *, method: str = "SPX_BARS") -> Dict[str, Any]:
    decision = get_decision(decision_id)
    if not decision:
        raise KeyError("decision not found")
    if decision.get("outcome"):
        return {"ok": True, "duplicate": True, "outcome": decision["outcome"]}
    series = _normalize_bars(bars)
    if not series:
        raise ValueError("at least one valid OHLC bar is required")
    entry = _f(decision.get("entry_price"), series[0]["open"])
    bullish = decision["direction"] in {"CALL", "LONG", "BULLISH"}
    stop, target = decision.get("stop_price"), decision.get("target_price")
    mfe = mae = 0.0
    stop_hit = target_hit = False
    exit_reason, exit_time, exit_price = "HORIZON_CLOSE", series[-1]["timestamp"], series[-1]["close"]
    for bar in series:
        favorable = (bar["high"] - entry) if bullish else (entry - bar["low"])
        adverse = (entry - bar["low"]) if bullish else (bar["high"] - entry)
        mfe, mae = max(mfe, favorable), max(mae, adverse)
        hit_stop = bool(stop) and ((bar["low"] <= stop) if bullish else (bar["high"] >= stop))
        hit_target = bool(target) and ((bar["high"] >= target) if bullish else (bar["low"] <= target))
        if hit_stop and hit_target:
            stop_hit = target_hit = True
            exit_reason, exit_time, exit_price = "AMBIGUOUS_SAME_BAR_STOP_FIRST", bar["timestamp"], float(stop)
            break
        if hit_stop:
            stop_hit = True; exit_reason, exit_time, exit_price = "STOP_HIT", bar["timestamp"], float(stop); break
        if hit_target:
            target_hit = True; exit_reason, exit_time, exit_price = "TARGET_HIT", bar["timestamp"], float(target); break
    realized = (exit_price - entry) if bullish else (entry - exit_price)
    grade = "AMBIGUOUS" if stop_hit and target_hit else "WIN" if realized > 0 else "LOSS" if realized < 0 else "FLAT"
    payload = {"grade": grade, "entry_price": entry, "exit_price": exit_price, "exit_reason": exit_reason,
               "exit_time": exit_time, "mfe_points": round(mfe, 4), "mae_points": round(mae, 4),
               "realized_points": round(realized, 4), "target_hit": target_hit, "stop_hit": stop_hit,
               "bars_evaluated": len(series), "direction": decision["direction"], "method": method}
    outcome_id, graded_at = str(uuid.uuid4()), _now()
    outcome_hash = _hash({"decision_id": decision_id, **payload})
    with _connect() as conn:
        conn.execute("""INSERT INTO apex_evidence_outcomes
        (outcome_id,decision_id,graded_at,grade,exit_reason,exit_time,exit_price,mfe_points,mae_points,realized_points,
         target_hit,stop_hit,bars_evaluated,grading_method,outcome_json,outcome_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
         (outcome_id, decision_id, graded_at, grade, exit_reason, exit_time, exit_price, payload["mfe_points"],
          payload["mae_points"], payload["realized_points"], int(target_hit), int(stop_hit), len(series), method,
          _canonical(payload), outcome_hash))
        # Immutable snapshots remain immutable; grading state is derived by join, not an UPDATE.
        _record_event(conn, decision_id, "OUTCOME_GRADED", {"outcome_hash": outcome_hash, "grade": grade})
        row = conn.execute("SELECT * FROM apex_evidence_outcomes WHERE decision_id=?", (decision_id,)).fetchone()
    return {"ok": True, "duplicate": False, "outcome": _outcome(row)}


def calibration_summary() -> Dict[str, Any]:
    bands = [(0, 49, "0-49"), (50, 74, "50-74"), (75, 84, "75-84"), (85, 100, "85-100")]
    with _connect() as conn:
        rows = conn.execute("""SELECT d.confidence,d.direction,o.grade,o.realized_points,o.mfe_points,o.mae_points
        FROM apex_evidence_decisions d JOIN apex_evidence_outcomes o ON o.decision_id=d.decision_id""").fetchall()
    result = []
    for low, high, label in bands:
        sample = [r for r in rows if low <= r["confidence"] <= high]
        wins = sum(r["grade"] == "WIN" for r in sample)
        result.append({"band": label, "count": len(sample), "wins": wins,
                       "win_rate_pct": round(wins / len(sample) * 100, 1) if sample else None,
                       "avg_realized_points": round(sum(r["realized_points"] for r in sample) / len(sample), 3) if sample else None,
                       "avg_mfe_points": round(sum(r["mfe_points"] for r in sample) / len(sample), 3) if sample else None,
                       "avg_mae_points": round(sum(r["mae_points"] for r in sample) / len(sample), 3) if sample else None})
    monotonic = None
    populated = [b for b in result if b["count"] >= 10]
    if len(populated) >= 2:
        monotonic = all(populated[i]["win_rate_pct"] <= populated[i+1]["win_rate_pct"] for i in range(len(populated)-1))
    return {"graded_decisions": len(rows), "bands": result, "confidence_monotonic": monotonic,
            "minimum_samples_per_band": 10, "policy_mutation_enabled": False}


def verify_evidence_integrity() -> Dict[str, Any]:
    errors: List[str] = []
    with _connect() as conn:
        decisions = conn.execute("SELECT * FROM apex_evidence_decisions").fetchall()
        for row in decisions:
            item = _decision(row)
            expected = _hash({"decision_id": item["decision_id"], **{k: item[k] for k in (
                "trade_id","symbol","decision_time","decision_state","direction","confidence","entry_price","stop_price",
                "target_price","horizon_minutes","feature_vector","engine_attribution","lineage_id")},
                "source_snapshot": item["source_snapshot"]})
            if expected != item["snapshot_hash"]:
                errors.append(f"SNAPSHOT_HASH_MISMATCH:{item['decision_id']}")
        events = conn.execute("SELECT * FROM apex_evidence_events ORDER BY decision_id,occurred_at,rowid").fetchall()
        previous: Dict[str, str] = {}
        for row in events:
            payload = _parse_json(row["payload_json"], {})
            expected = _hash({"event_id": row["event_id"], "decision_id": row["decision_id"],
                              "event_type": row["event_type"], "occurred_at": row["occurred_at"],
                              "payload": payload, "previous_hash": row["previous_hash"] or ""})
            if row["previous_hash"] != previous.get(row["decision_id"], "") or row["integrity_hash"] != expected:
                errors.append(f"EVENT_CHAIN_MISMATCH:{row['event_id']}")
            previous[row["decision_id"]] = row["integrity_hash"]
    return {"status": "VERIFIED" if not errors else "TAMPER_DETECTED", "errors": errors,
            "decision_count": len(decisions), "event_count": len(events)}


def build_institutional_evidence(context: Optional[Mapping[str, Any]] = None, *, auto_capture: bool = True) -> Dict[str, Any]:
    ctx = dict(context or {})
    capture = None
    if auto_capture:
        try:
            capture = capture_decision(ctx)
        except Exception as exc:
            capture = {"ok": False, "captured": False, "state": "CAPTURE_ERROR", "error": str(exc)}
    with _connect() as conn:
        counts = conn.execute("""SELECT COUNT(*) total,
          SUM(CASE WHEN o.decision_id IS NOT NULL THEN 1 ELSE 0 END) graded
          FROM apex_evidence_decisions d LEFT JOIN apex_evidence_outcomes o ON o.decision_id=d.decision_id""").fetchone()
        latest = conn.execute("""SELECT d.decision_id,d.decision_time,d.decision_state,d.direction,d.confidence,o.grade,o.realized_points
          FROM apex_evidence_decisions d LEFT JOIN apex_evidence_outcomes o ON o.decision_id=d.decision_id
          ORDER BY d.decision_time DESC LIMIT 10""").fetchall()
    total, graded = int(counts["total"] or 0), int(counts["graded"] or 0)
    calibration = calibration_summary()
    return {"version": VERSION, "evidence_state": "VALIDATING" if graded else "CAPTURE_REQUIRED",
            "decision_count": total, "graded_count": graded, "ungraded_count": total-graded,
            "coverage_pct": round(graded / total * 100, 1) if total else 0.0,
            "capture_result": capture, "calibration": calibration,
            "integrity": verify_evidence_integrity(), "latest_decisions": [dict(r) for r in latest],
            "controls": {"immutable_snapshots": True, "immutable_outcomes": True, "automatic_weight_updates": False,
                         "live_execution": False, "minimum_graded_decisions_before_policy_review": 100},
            "blockers": (["NO_DECISIONS_CAPTURED"] if not total else []) + (["FEWER_THAN_100_GRADED_DECISIONS"] if graded < 100 else []),
            "safety_note": "Phase 31 measures existing decisions only. It cannot change weights, policy, authorization, risk, or broker state."}
