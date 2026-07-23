"""APEX Trade Director Phase 22 — Institutional Learning & Adaptive Intelligence.

This module turns completed Phase 21 trade lifecycles into a durable learning
ledger and produces advisory calibration, attribution, similarity, and feedback.
It performs no provider or broker calls and never mutates live risk/authorization.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from engine.trade_director_lifecycle_contracts import as_mapping, normalize_trade_context, utc_now_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS institutional_learning_ledger (
    learning_id TEXT PRIMARY KEY,
    trade_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT,
    strategy TEXT,
    contract_symbol TEXT,
    entered_at TEXT,
    closed_at TEXT,
    decision_confidence REAL,
    realized_pnl REAL,
    r_multiple REAL,
    mfe REAL,
    mae REAL,
    duration_minutes REAL,
    win INTEGER,
    market_context_json TEXT NOT NULL,
    decision_context_json TEXT NOT NULL,
    execution_context_json TEXT NOT NULL,
    outcome_context_json TEXT NOT NULL,
    learning_context_json TEXT NOT NULL,
    engine_evidence_json TEXT NOT NULL,
    feature_vector_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(trade_id)
);
CREATE INDEX IF NOT EXISTS idx_ill_closed_at ON institutional_learning_ledger(closed_at DESC);
CREATE INDEX IF NOT EXISTS idx_ill_strategy ON institutional_learning_ledger(strategy, closed_at DESC);
CREATE INDEX IF NOT EXISTS idx_ill_symbol ON institutional_learning_ledger(symbol, closed_at DESC);
"""


def _f(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _u(value: Any) -> str:
    return str(value or "").strip().upper()


def learning_db_path() -> str:
    configured = os.getenv("APEX_TRADE_LEARNING_DB", "").strip()
    if configured:
        return configured
    if os.path.isdir("/data") and os.access("/data", os.W_OK):
        return "/data/apex_trade_learning.db"
    return os.path.join(os.getcwd(), "apex_trade_learning.db")


def _connect() -> sqlite3.Connection:
    path = learning_db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=4.0)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _json(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"), sort_keys=True)


def _loads(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except Exception:
        return default


def _feature_vector(context: Mapping[str, Any], outcome: Mapping[str, Any]) -> Dict[str, Any]:
    tc = normalize_trade_context(context)
    session = as_mapping(as_mapping(tc["session"]).get("session"))
    memory = as_mapping(tc["market_memory"])
    cross = as_mapping(tc["cross_asset"])
    strategy = as_mapping(tc["strategy"])
    mtf = as_mapping(tc["multi_timeframe"])
    flow = as_mapping(tc["institutional_flow"])
    decision = as_mapping(tc["decision"])
    position = as_mapping(tc["position"])
    return {
        "symbol": _u(tc["symbol"]),
        "direction": _u(decision.get("dominant_direction") or position.get("side")),
        "strategy": _u(strategy.get("selected_strategy") or strategy.get("strategy")),
        "session_mode": _u(session.get("mode")),
        "regime": _u(memory.get("regime") or memory.get("market_regime") or context.get("regime")),
        "cross_asset_bias": _u(cross.get("dominant_direction") or cross.get("bias")),
        "mtf_gate": _u(mtf.get("decision_gate")),
        "flow_gate": _u(flow.get("decision_gate")),
        "flow_bias": _u(flow.get("institutional_bias") or flow.get("dominant_direction")),
        "confidence": round(_f(decision.get("confidence"), 0.0) or 0.0, 2),
        "duration_bucket": "LT5" if (_f(outcome.get("duration_minutes"), 0.0) or 0) < 5 else "5TO15" if (_f(outcome.get("duration_minutes"), 0.0) or 0) <= 15 else "GT15",
    }


def _decision_quality(outcome: Mapping[str, Any]) -> Dict[str, Any]:
    pnl = _f(outcome.get("realized_pnl"), 0.0) or 0.0
    r = _f(outcome.get("r_multiple"), None)
    mfe = _f(outcome.get("mfe") or outcome.get("max_favorable_excursion"), None)
    mae = _f(outcome.get("mae") or outcome.get("max_adverse_excursion"), None)
    exit_eff = None
    if mfe not in (None, 0):
        captured = _f(outcome.get("captured_move") or outcome.get("realized_move"), None)
        if captured is not None:
            exit_eff = round(max(-100.0, min(100.0, captured / mfe * 100.0)), 1)
    score = 50.0
    score += 20 if pnl > 0 else -20 if pnl < 0 else 0
    if r is not None:
        score += max(-20, min(20, r * 10))
    if mae is not None and mfe is not None and abs(mae) + abs(mfe) > 0:
        score += max(-10, min(10, (abs(mfe) - abs(mae)) / (abs(mfe) + abs(mae)) * 10))
    score = round(max(0.0, min(100.0, score)), 1)
    return {
        "decision_quality_score": score,
        "direction_correct": bool(outcome.get("direction_correct", pnl > 0)),
        "entry_timing": str(outcome.get("entry_timing") or "UNASSESSED").upper(),
        "exit_timing": str(outcome.get("exit_timing") or "UNASSESSED").upper(),
        "exit_efficiency_pct": exit_eff,
        "stop_quality": str(outcome.get("stop_quality") or "UNASSESSED").upper(),
        "management_quality": str(outcome.get("management_quality") or "UNASSESSED").upper(),
    }


def archive_learning_record(context: Mapping[str, Any], outcome: Mapping[str, Any]) -> Dict[str, Any]:
    tc = normalize_trade_context(context)
    position = as_mapping(tc["position"])
    decision = as_mapping(tc["decision"])
    strategy = as_mapping(tc["strategy"])
    contract = as_mapping(as_mapping(tc["contract"]).get("best_contract") or as_mapping(tc["contract"]).get("selected_contract"))
    lifecycle = as_mapping(context.get("trade_lifecycle"))
    trade_id = str(outcome.get("trade_id") or position.get("trade_id") or lifecycle.get("lifecycle_id") or ("ATD-" + uuid.uuid4().hex[:12].upper()))
    learning_id = "L22-" + uuid.uuid5(uuid.NAMESPACE_URL, trade_id).hex[:16].upper()
    now = utc_now_iso()
    pnl = _f(outcome.get("realized_pnl"), 0.0) or 0.0
    r_mult = _f(outcome.get("r_multiple"), None)
    mfe = _f(outcome.get("mfe") or outcome.get("max_favorable_excursion"), None)
    mae = _f(outcome.get("mae") or outcome.get("max_adverse_excursion"), None)
    duration = _f(outcome.get("duration_minutes") or position.get("minutes_held"), 0.0) or 0.0
    quality = _decision_quality(outcome)
    features = _feature_vector(context, {**dict(outcome), "duration_minutes": duration})
    engine_evidence = list(lifecycle.get("provenance") or [])
    market_context = {
        "session": tc["session"], "market_memory": tc["market_memory"],
        "cross_asset": tc["cross_asset"], "multi_timeframe": tc["multi_timeframe"],
        "institutional_flow": tc["institutional_flow"],
    }
    decision_context = {
        "decision_intelligence": tc["decision_intelligence"], "governed_decision": tc["decision"],
        "strategy": tc["strategy"], "contract": tc["contract"],
    }
    execution_context = {"execution": tc["execution"], "position": tc["position"], "trade_lifecycle": lifecycle}
    normalized_outcome = {
        "realized_pnl": pnl, "r_multiple": r_mult, "mfe": mfe, "mae": mae,
        "duration_minutes": duration, "exit_reason": outcome.get("exit_reason"),
        "exit_price": outcome.get("exit_price"), "notes": str(outcome.get("notes") or "").strip(),
        "source": str(outcome.get("source") or "USER_CONFIRMED"),
    }
    learning_context = {**quality, "what_worked": outcome.get("what_worked") or [], "what_failed": outcome.get("what_failed") or [], "improvement": outcome.get("improvement") or []}
    values = (
        learning_id, trade_id, str(tc["symbol"]), features["direction"], features["strategy"],
        contract.get("symbol"), position.get("entered_at_iso") or position.get("entered_at"),
        outcome.get("closed_at") or now, features["confidence"], pnl, r_mult, mfe, mae, duration,
        1 if pnl > 0 else 0, _json(market_context), _json(decision_context), _json(execution_context),
        _json(normalized_outcome), _json(learning_context), _json(engine_evidence), _json(features), now, now,
    )
    with _connect() as conn:
        conn.execute(
            """INSERT INTO institutional_learning_ledger
            (learning_id,trade_id,symbol,direction,strategy,contract_symbol,entered_at,closed_at,
             decision_confidence,realized_pnl,r_multiple,mfe,mae,duration_minutes,win,
             market_context_json,decision_context_json,execution_context_json,outcome_context_json,
             learning_context_json,engine_evidence_json,feature_vector_json,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(trade_id) DO UPDATE SET
              closed_at=excluded.closed_at, realized_pnl=excluded.realized_pnl,
              r_multiple=excluded.r_multiple, mfe=excluded.mfe, mae=excluded.mae,
              duration_minutes=excluded.duration_minutes, win=excluded.win,
              outcome_context_json=excluded.outcome_context_json,
              learning_context_json=excluded.learning_context_json,
              feature_vector_json=excluded.feature_vector_json, updated_at=excluded.updated_at""",
            values,
        )
    return {"ok": True, "learning_id": learning_id, "trade_id": trade_id, "record": get_learning_record(trade_id)}


def _decode(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "learning_id": row["learning_id"], "trade_id": row["trade_id"], "symbol": row["symbol"],
        "direction": row["direction"], "strategy": row["strategy"], "contract_symbol": row["contract_symbol"],
        "entered_at": row["entered_at"], "closed_at": row["closed_at"],
        "decision_confidence": row["decision_confidence"], "realized_pnl": row["realized_pnl"],
        "r_multiple": row["r_multiple"], "mfe": row["mfe"], "mae": row["mae"],
        "duration_minutes": row["duration_minutes"], "win": bool(row["win"]),
        "market_context": _loads(row["market_context_json"], {}),
        "decision_context": _loads(row["decision_context_json"], {}),
        "execution_context": _loads(row["execution_context_json"], {}),
        "outcome_context": _loads(row["outcome_context_json"], {}),
        "learning_context": _loads(row["learning_context_json"], {}),
        "engine_evidence": _loads(row["engine_evidence_json"], []),
        "feature_vector": _loads(row["feature_vector_json"], {}),
        "updated_at": row["updated_at"],
    }


def get_learning_record(trade_id: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM institutional_learning_ledger WHERE trade_id=? OR learning_id=?", (trade_id, trade_id)).fetchone()
    return _decode(row) if row else None


def learning_history(limit: int = 100) -> List[Dict[str, Any]]:
    limit = max(1, min(1000, int(limit)))
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM institutional_learning_ledger ORDER BY closed_at DESC LIMIT ?", (limit,)).fetchall()
    return [_decode(row) for row in rows]


def _bucket(confidence: float) -> str:
    lo = int(max(0, min(90, confidence // 10 * 10)))
    return f"{lo:02d}-{lo+9:02d}"


def confidence_calibration(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    buckets: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in records:
        buckets[_bucket(float(row.get("decision_confidence") or 0))].append(row)
    output = []
    weighted_error = 0.0
    samples = 0
    for name in sorted(buckets):
        rows = buckets[name]
        actual = sum(1 for r in rows if r.get("win")) / len(rows) * 100.0
        expected = sum(float(r.get("decision_confidence") or 0) for r in rows) / len(rows)
        error = actual - expected
        weighted_error += abs(error) * len(rows)
        samples += len(rows)
        output.append({"bucket": name, "samples": len(rows), "expected_win_rate": round(expected, 1), "actual_win_rate": round(actual, 1), "calibration_error": round(error, 1)})
    return {"buckets": output, "mean_absolute_calibration_error": round(weighted_error / samples, 1) if samples else None, "samples": samples}


def engine_attribution(records: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    stats: Dict[str, Dict[str, float]] = defaultdict(lambda: {"samples": 0.0, "wins": 0.0, "r": 0.0})
    for row in records:
        for evidence in row.get("engine_evidence") or []:
            name = str(evidence.get("engine") or "UNKNOWN")
            value = _u(evidence.get("value"))
            if value in {"UNKNOWN", "", "STAND_DOWN", "DECISION_BLOCKED"}:
                continue
            stats[name]["samples"] += 1
            stats[name]["wins"] += 1 if row.get("win") else 0
            stats[name]["r"] += float(row.get("r_multiple") or 0)
    rows = []
    for name, s in stats.items():
        n = int(s["samples"])
        rows.append({"engine": name, "samples": n, "win_rate": round(s["wins"] / n * 100, 1), "average_r": round(s["r"] / n, 2), "status": "PROVISIONAL" if n < 30 else "CALIBRATING" if n < 100 else "ESTABLISHED"})
    return sorted(rows, key=lambda x: (-x["samples"], -x["win_rate"], x["engine"]))


def strategy_scorecards(records: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in records:
        groups[str(row.get("strategy") or "UNCLASSIFIED")].append(row)
    output = []
    for strategy, rows in groups.items():
        pnls = [float(r.get("realized_pnl") or 0) for r in rows]
        rs = [float(r.get("r_multiple") or 0) for r in rows if r.get("r_multiple") is not None]
        gross_win = sum(v for v in pnls if v > 0); gross_loss = abs(sum(v for v in pnls if v < 0))
        output.append({
            "strategy": strategy, "samples": len(rows),
            "win_rate": round(sum(1 for r in rows if r.get("win")) / len(rows) * 100, 1),
            "expectancy_r": round(sum(rs) / len(rs), 2) if rs else None,
            "average_pnl": round(sum(pnls) / len(pnls), 2),
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
            "status": "PROVISIONAL" if len(rows) < 30 else "CALIBRATING" if len(rows) < 100 else "ESTABLISHED",
        })
    return sorted(output, key=lambda x: (-x["samples"], x["strategy"]))


def _similarity(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    weighted = {"symbol": 1.0, "direction": 1.5, "strategy": 2.0, "session_mode": 0.7, "regime": 1.5, "cross_asset_bias": 0.8, "mtf_gate": 1.2, "flow_gate": 1.2, "flow_bias": 1.0, "duration_bucket": 0.4}
    total = sum(weighted.values()); score = 0.0
    for key, weight in weighted.items():
        av, bv = _u(a.get(key)), _u(b.get(key))
        if av and bv and av == bv:
            score += weight
    ac = float(a.get("confidence") or 0); bc = float(b.get("confidence") or 0)
    score += max(0.0, 1.0 - abs(ac - bc) / 100.0)
    total += 1.0
    return round(score / total * 100.0, 1)


def similar_trades(context: Mapping[str, Any], records: Sequence[Mapping[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    current = _feature_vector(context, {})
    ranked = []
    for row in records:
        similarity = _similarity(current, as_mapping(row.get("feature_vector")))
        ranked.append({"trade_id": row.get("trade_id"), "closed_at": row.get("closed_at"), "strategy": row.get("strategy"), "direction": row.get("direction"), "similarity": similarity, "win": row.get("win"), "r_multiple": row.get("r_multiple"), "realized_pnl": row.get("realized_pnl")})
    return sorted(ranked, key=lambda x: (-x["similarity"], str(x["closed_at"])), reverse=False)[:max(1, min(limit, 20))]


def build_learning_intelligence(context: Optional[Mapping[str, Any]] = None, *, limit: int = 500) -> Dict[str, Any]:
    records = learning_history(limit)
    calibration = confidence_calibration(records)
    strategies = strategy_scorecards(records)
    attribution = engine_attribution(records)
    similar = similar_trades(context or {}, records, 5) if context else []
    total = len(records); wins = sum(1 for r in records if r.get("win"))
    rs = [float(r.get("r_multiple") or 0) for r in records if r.get("r_multiple") is not None]
    quality = [float(as_mapping(r.get("learning_context")).get("decision_quality_score") or 0) for r in records]
    recommendations = []
    if total < 30:
        recommendations.append("Continue collecting user-confirmed outcomes; all adaptive findings remain provisional until at least 30 comparable trades exist.")
    if calibration.get("mean_absolute_calibration_error") is not None and calibration["mean_absolute_calibration_error"] > 15:
        recommendations.append("Confidence is materially miscalibrated; use the calibration output as advisory evidence for Phase 19/20 review, not as an automatic threshold change.")
    weak = [s for s in strategies if s["samples"] >= 5 and (s["expectancy_r"] or 0) < 0]
    if weak:
        recommendations.append("Review negative-expectancy strategy cohorts before increasing their decision weight: " + ", ".join(s["strategy"] for s in weak[:3]) + ".")
    similar_summary = None
    if similar:
        cohort = [r for r in similar if r["similarity"] >= 60]
        if cohort:
            similar_summary = {"samples": len(cohort), "win_rate": round(sum(1 for r in cohort if r["win"]) / len(cohort) * 100, 1), "average_r": round(sum(float(r.get("r_multiple") or 0) for r in cohort) / len(cohort), 2)}
    return {
        "version": "PHASE_22", "as_of": utc_now_iso(), "mode": "INSTITUTIONAL_LEARNING_ADVISORY",
        "learning_state": "COLLECTING" if total < 30 else "CALIBRATING" if total < 100 else "ESTABLISHED",
        "summary": {"trades_learned": total, "win_rate": round(wins / total * 100, 1) if total else None, "expectancy_r": round(sum(rs) / len(rs), 2) if rs else None, "average_decision_quality": round(sum(quality) / len(quality), 1) if quality else None},
        "confidence_calibration": calibration, "engine_attribution": attribution,
        "strategy_scorecards": strategies, "similar_trades": similar, "similar_cohort": similar_summary,
        "adaptive_recommendations": recommendations,
        "feedback_contract": {"phase14_strategy_selection": "ADVISORY", "phase15_contract_ranking": "ADVISORY", "phase19_evidence_weighting": "ADVISORY", "phase20_authorization_thresholds": "ADVISORY", "phase21_management": "ADVISORY", "automatic_live_mutation": False},
        "database": learning_db_path(),
        "safety_note": "Phase 22 measures and recommends only. It cannot retrain live models automatically, alter risk limits, change authorization thresholds, override Phase 20/21, contact a broker, or submit/modify orders.",
    }
