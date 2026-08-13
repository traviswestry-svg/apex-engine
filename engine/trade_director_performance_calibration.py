"""APEX Trade Director Phase 32 — Performance & Calibration Center.

Read-only analytics over Phase 31 immutable evidence. This module never changes
scores, thresholds, policies, risk, authorization, or broker state.
"""
from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from zoneinfo import ZoneInfo

from engine.trade_director_institutional_evidence import evidence_db_path, initialize_evidence_store

VERSION = "PHASE_32"
MIN_DIRECTIONAL_SAMPLES = 20
MIN_CALIBRATION_SAMPLES = 100
MIN_ATTRIBUTION_SAMPLES = 30


def _connect() -> sqlite3.Connection:
    initialize_evidence_store()
    conn = sqlite3.connect(evidence_db_path(), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _json(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if isinstance(value, str) else value
    except Exception:
        return default


def _num(value: Any) -> Optional[float]:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _rows(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    sql = """SELECT d.*,o.grade,o.exit_reason,o.exit_time,o.exit_price,o.mfe_points,o.mae_points,
             o.realized_points,o.target_hit,o.stop_hit,o.bars_evaluated,o.grading_method,o.graded_at
             FROM apex_evidence_decisions d JOIN apex_evidence_outcomes o ON o.decision_id=d.decision_id
             ORDER BY d.decision_time DESC"""
    params: Tuple[Any, ...] = ()
    if limit:
        sql += " LIMIT ?"; params = (max(1, min(int(limit), 5000)),)
    with _connect() as conn:
        raw = conn.execute(sql, params).fetchall()
    result = []
    for row in raw:
        item = dict(row)
        item["feature_vector"] = _json(item.pop("feature_vector_json"), {})
        item["engine_attribution"] = _json(item.pop("engine_attribution_json"), {})
        item["source_snapshot"] = _json(item.pop("source_snapshot_json"), {})
        result.append(item)
    return result


def _valid(rows: Iterable[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    return [r for r in rows if str(r.get("grade")) in {"WIN", "LOSS", "FLAT"}]


def _stats(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    sample = list(rows)
    valid = _valid(sample)
    wins = sum(str(r.get("grade")) == "WIN" for r in valid)
    realized = [_num(r.get("realized_points")) or 0.0 for r in valid]
    mfe = [_num(r.get("mfe_points")) or 0.0 for r in valid]
    mae = [_num(r.get("mae_points")) or 0.0 for r in valid]
    gross_win = sum(x for x in realized if x > 0)
    gross_loss = abs(sum(x for x in realized if x < 0))
    return {
        "count": len(sample), "scored_count": len(valid), "wins": wins,
        "win_rate_pct": round(100 * wins / len(valid), 2) if valid else None,
        "expectancy_points": round(sum(realized) / len(valid), 4) if valid else None,
        "avg_mfe_points": round(sum(mfe) / len(valid), 4) if valid else None,
        "avg_mae_points": round(sum(mae) / len(valid), 4) if valid else None,
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss else (None if not gross_win else "INF"),
        "ambiguous_count": sum(str(r.get("grade")) == "AMBIGUOUS" for r in sample),
    }


def _session(decision_time: Any) -> str:
    try:
        dt = datetime.fromisoformat(str(decision_time).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        local = dt.astimezone(ZoneInfo("America/New_York"))
        minutes = local.hour * 60 + local.minute
        if minutes < 570: return "PREMARKET"
        if minutes < 630: return "OPEN_0930_1030"
        if minutes < 690: return "MORNING_1030_1130"
        if minutes < 810: return "MIDDAY_1130_1330"
        if minutes < 930: return "AFTERNOON_1330_1530"
        if minutes <= 960: return "POWER_HOUR_1530_1600"
        return "AFTER_HOURS"
    except Exception:
        return "UNKNOWN"


def performance_summary() -> Dict[str, Any]:
    rows = _rows()
    overall = _stats(rows)
    by_direction = {k: _stats([r for r in rows if str(r.get("direction")) == k]) for k in ("CALL", "PUT", "LONG", "SHORT", "BULLISH", "BEARISH")}
    by_direction = {k: v for k, v in by_direction.items() if v["count"]}
    sessions: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows: sessions[_session(row.get("decision_time"))].append(row)
    by_session = {k: _stats(v) for k, v in sorted(sessions.items())}
    states: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows: states[str(row.get("decision_state") or "UNKNOWN")].append(row)
    return {
        "version": VERSION, "overall": overall, "by_direction": by_direction,
        "by_session": by_session, "by_decision_state": {k: _stats(v) for k, v in states.items()},
        "latest_graded_at": rows[0].get("graded_at") if rows else None,
        "sample_gate": {"minimum": MIN_CALIBRATION_SAMPLES, "current": overall["scored_count"],
                        "met": overall["scored_count"] >= MIN_CALIBRATION_SAMPLES},
    }


def confidence_reliability() -> Dict[str, Any]:
    rows = _valid(_rows())
    bands = [(0,49),(50,59),(60,69),(70,74),(75,79),(80,84),(85,89),(90,94),(95,100)]
    reliability = []
    weighted_error = 0.0
    brier_values = []
    for low, high in bands:
        sample = [r for r in rows if low <= float(r.get("confidence") or 0) <= high]
        if not sample: continue
        predicted = sum(float(r.get("confidence") or 0) / 100 for r in sample) / len(sample)
        actual = sum(str(r.get("grade")) == "WIN" for r in sample) / len(sample)
        gap = actual - predicted
        weighted_error += len(sample) * abs(gap)
        reliability.append({"band": f"{low}-{high}", "count": len(sample),
                            "predicted_win_pct": round(predicted*100,2), "actual_win_pct": round(actual*100,2),
                            "calibration_gap_pct": round(gap*100,2)})
    for r in rows:
        p = max(0.0, min(1.0, float(r.get("confidence") or 0) / 100))
        y = 1.0 if str(r.get("grade")) == "WIN" else 0.0
        brier_values.append((p-y)**2)
    ece = weighted_error / len(rows) if rows else None
    monotonic = None
    eligible = [b for b in reliability if b["count"] >= 10]
    if len(eligible) >= 2:
        monotonic = all(eligible[i]["actual_win_pct"] <= eligible[i+1]["actual_win_pct"] for i in range(len(eligible)-1))
    return {"version": VERSION, "graded_decisions": len(rows), "bands": reliability,
            "brier_score": round(sum(brier_values)/len(brier_values), 5) if brier_values else None,
            "expected_calibration_error": round(ece, 5) if ece is not None else None,
            "confidence_monotonic": monotonic, "minimum_samples": MIN_CALIBRATION_SAMPLES,
            "calibration_state": "REVIEW_READY" if len(rows) >= MIN_CALIBRATION_SAMPLES else "COLLECTING_EVIDENCE"}


def _extract_engine_scores(attribution: Mapping[str, Any]) -> Dict[str, float]:
    result: Dict[str, float] = {}
    for name, value in attribution.items():
        score = _num(value)
        if score is None and isinstance(value, Mapping):
            for key in ("contribution", "score", "confidence", "weight", "value"):
                score = _num(value.get(key))
                if score is not None: break
        if score is not None: result[str(name)] = score
    return result


def engine_attribution() -> Dict[str, Any]:
    rows = _valid(_rows())
    overall = _stats(rows)
    buckets: Dict[str, List[Tuple[float, Mapping[str, Any]]]] = defaultdict(list)
    for row in rows:
        attribution = row.get("engine_attribution") or {}
        if not attribution:
            snapshot = row.get("source_snapshot") or {}
            attribution = snapshot.get("engine_attribution") or snapshot.get("confidence_attribution") or {}
        for name, score in _extract_engine_scores(attribution).items():
            buckets[name].append((score, row))
    engines = []
    for name, values in buckets.items():
        scores = sorted(v[0] for v in values)
        median = scores[len(scores)//2]
        high = [r for score, r in values if score >= median]
        low = [r for score, r in values if score < median]
        high_stats, low_stats = _stats(high), _stats(low)
        lift = None
        if high_stats["expectancy_points"] is not None and low_stats["expectancy_points"] is not None:
            lift = round(high_stats["expectancy_points"] - low_stats["expectancy_points"], 4)
        engines.append({"engine": name, "samples": len(values), "median_score": round(median,4),
                        "high_score_results": high_stats, "low_score_results": low_stats,
                        "expectancy_lift_points": lift,
                        "evidence_state": "ATTRIBUTION_READY" if len(values) >= MIN_ATTRIBUTION_SAMPLES else "INSUFFICIENT_SAMPLE"})
    engines.sort(key=lambda x: (x["samples"], abs(x["expectancy_lift_points"] or 0)), reverse=True)
    return {"version": VERSION, "overall": overall, "engines": engines,
            "minimum_samples_per_engine": MIN_ATTRIBUTION_SAMPLES,
            "method": "MEDIAN_SPLIT_DESCRIPTIVE_NOT_CAUSAL",
            "warning": "Attribution is descriptive. Correlated engines must not be interpreted as independent causal edge."}


def decision_ledger(limit: int = 100, direction: Optional[str] = None, grade: Optional[str] = None) -> Dict[str, Any]:
    rows = _rows(limit=5000)
    if direction: rows = [r for r in rows if str(r.get("direction")) == direction.upper()]
    if grade: rows = [r for r in rows if str(r.get("grade")) == grade.upper()]
    items = []
    for r in rows[:max(1, min(int(limit), 1000))]:
        items.append({k: r.get(k) for k in ("decision_id","decision_time","decision_state","direction","confidence",
                     "entry_price","stop_price","target_price","grade","exit_reason","exit_time","exit_price",
                     "mfe_points","mae_points","realized_points","bars_evaluated","grading_method","snapshot_hash","outcome_hash")})
    return {"version": VERSION, "count": len(items), "items": items, "filters": {"direction": direction, "grade": grade}}


def build_performance_calibration_center() -> Dict[str, Any]:
    performance = performance_summary()
    calibration = confidence_reliability()
    attribution = engine_attribution()
    n = performance["overall"]["scored_count"]
    blockers = []
    if n < MIN_CALIBRATION_SAMPLES: blockers.append("FEWER_THAN_100_GRADED_DECISIONS")
    if not attribution["engines"]: blockers.append("NO_ENGINE_ATTRIBUTION_CAPTURED")
    if calibration["confidence_monotonic"] is False: blockers.append("CONFIDENCE_NOT_MONOTONIC")
    return {"version": VERSION, "analytics_state": "REVIEW_READY" if not blockers else "COLLECTING_EVIDENCE",
            "performance": performance, "calibration": calibration, "engine_attribution": attribution,
            "blockers": blockers,
            "controls": {"read_only": True, "automatic_weight_updates": False, "threshold_mutation": False,
                         "policy_promotion": False, "broker_access": False},
            "safety_note": "Phase 32 analyzes immutable Phase 31 evidence only. Results are descriptive until sample gates and governed validation are satisfied."}
