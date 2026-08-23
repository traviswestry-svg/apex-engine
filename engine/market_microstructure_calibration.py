"""APEX 68.9.0 — Microstructure Calibration & Decision-Evidence Promotion Governance.

This module evaluates *persisted real L2/MBO observations* and explicitly graded
forward outcomes.  It can produce a shadow confirmation score and promotion
readiness assessment, but it cannot mutate APEX decision confidence, action,
execution, or production policy.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import os
from typing import Any, Mapping, Sequence

from .market_microstructure_store import MicrostructureStore

VERSION = "68.9.0"
SCHEMA_VERSION = "apex.market_microstructure.calibration.v1"


def _f(v: Any, default: float | None = None) -> float | None:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_ts(v: Any) -> datetime | None:
    try:
        s = str(v or "").strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _wilson(successes: int, n: int, z: float = 1.959963984540054) -> dict[str, float | None]:
    if n <= 0:
        return {"lower_pct": None, "upper_pct": None}
    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(max(0.0, p * (1 - p) / n + z2 / (4 * n * n)))
    return {"lower_pct": round(max(0.0, center - margin) * 100, 2), "upper_pct": round(min(1.0, center + margin) * 100, 2)}


def integrity_report(store: MicrostructureStore, instrument: str = "ES", *, limit: int = 1000,
                     max_age_seconds: int = 10) -> dict[str, Any]:
    rows = list(reversed(store.calibration_rows(instrument, limit=limit)))
    n = len(rows)
    now = datetime.now(timezone.utc)
    timestamps = [_parse_ts(r.get("observed_at")) for r in rows]
    monotonic = all(a is not None and b is not None and a <= b for a, b in zip(timestamps, timestamps[1:])) if n > 1 else bool(n)
    latest_dt = timestamps[-1] if timestamps else None
    age = max(0.0, (now - latest_dt).total_seconds()) if latest_dt else None

    seq_values: list[int] = []
    seq_parseable = True
    for r in rows:
        s = r.get("sequence_id")
        if s in (None, ""):
            seq_parseable = False
            break
        try:
            seq_values.append(int(s))
        except (TypeError, ValueError):
            seq_parseable = False
            break
    sequence_gaps = 0
    sequence_regressions = 0
    if seq_parseable and len(seq_values) > 1:
        for a, b in zip(seq_values, seq_values[1:]):
            if b <= a:
                sequence_regressions += 1
            elif b > a + 1:
                sequence_gaps += b - a - 1

    l2 = 0
    classified = 0
    source_names: set[str] = set()
    feed_quality: set[str] = set()
    for row in rows:
        analysis = row.get("analysis") if isinstance(row.get("analysis"), Mapping) else {}
        book = analysis.get("book") if isinstance(analysis.get("book"), Mapping) else {}
        execution = analysis.get("execution") if isinstance(analysis.get("execution"), Mapping) else {}
        l2 += int(bool(book.get("l2_available")))
        classified += int(bool(execution.get("true_delta_available")))
        source_names.add(str(row.get("source") or "UNSPECIFIED"))
        feed_quality.add(str(row.get("feed_quality") or "UNKNOWN").upper())

    l2_cov = l2 / n if n else 0.0
    delta_cov = classified / n if n else 0.0
    sequence_authoritative = bool(seq_parseable and n > 1 and sequence_gaps == 0 and sequence_regressions == 0)
    return {
        "ok": True,
        "status": "READY" if n and l2_cov >= 0.95 and delta_cov >= 0.95 and monotonic else "COLLECTING",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "instrument": instrument.upper(),
        "observations": n,
        "latest_age_seconds": round(age, 3) if age is not None else None,
        "fresh_for_live_use": bool(age is not None and age <= max_age_seconds),
        "timestamp_monotonic": monotonic,
        "l2_coverage_pct": round(l2_cov * 100, 2),
        "true_delta_coverage_pct": round(delta_cov * 100, 2),
        "sources": sorted(source_names),
        "feed_quality": sorted(feed_quality),
        "sequence": {
            "present_and_numeric": seq_parseable,
            "authoritative": sequence_authoritative,
            "gaps": sequence_gaps,
            "regressions": sequence_regressions,
            "note": "L2 snapshots may be useful without exchange sequence IDs; MBO-grade continuity cannot be claimed without them.",
        },
    }


def _direction_correct(signal: float | None, move_ticks: float | None) -> bool | None:
    if signal is None or move_ticks is None or signal == 0 or move_ticks == 0:
        return None
    return (signal > 0 and move_ticks > 0) or (signal < 0 and move_ticks < 0)


def calibration_report(store: MicrostructureStore, instrument: str = "ES", *, limit: int = 5000) -> dict[str, Any]:
    samples = store.calibration_samples(instrument, limit=limit)
    metrics = {
        "depth_imbalance_direction": {"eligible": 0, "correct": 0},
        "delta_direction": {"eligible": 0, "correct": 0},
        "absorption_reversal": {"eligible": 0, "correct": 0},
    }
    for row in samples:
        analysis = row.get("analysis") if isinstance(row.get("analysis"), Mapping) else {}
        outcome = row.get("outcome") if isinstance(row.get("outcome"), Mapping) else {}
        move = _f(outcome.get("forward_move_ticks"))
        book = analysis.get("book") if isinstance(analysis.get("book"), Mapping) else {}
        execution = analysis.get("execution") if isinstance(analysis.get("execution"), Mapping) else {}
        interaction = analysis.get("interaction") if isinstance(analysis.get("interaction"), Mapping) else {}

        for name, signal in (("depth_imbalance_direction", _f(book.get("depth_imbalance"))),
                             ("delta_direction", _f(execution.get("delta")))):
            correct = _direction_correct(signal, move)
            if correct is not None:
                metrics[name]["eligible"] += 1
                metrics[name]["correct"] += int(correct)

        absorption = interaction.get("absorption_candidate") if isinstance(interaction.get("absorption_candidate"), Mapping) else {}
        if absorption.get("detected") and move is not None and move != 0:
            side = str(absorption.get("side") or "")
            expected = -1.0 if side == "ASK_SELLER" else (1.0 if side == "BID_BUYER" else 0.0)
            if expected:
                metrics["absorption_reversal"]["eligible"] += 1
                metrics["absorption_reversal"]["correct"] += int((expected > 0 and move > 0) or (expected < 0 and move < 0))

    out_metrics: dict[str, Any] = {}
    for name, stat in metrics.items():
        n = stat["eligible"]
        wins = stat["correct"]
        rate = wins / n if n else None
        out_metrics[name] = {
            "eligible_samples": n,
            "correct": wins,
            "accuracy_pct": round(rate * 100, 2) if rate is not None else None,
            "confidence_interval_95": _wilson(wins, n),
        }

    return {
        "ok": True,
        "status": "READY" if samples else "COLLECTING",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "instrument": instrument.upper(),
        "labeled_samples": len(samples),
        "metrics": out_metrics,
        "governance": {
            "offline_shadow_calibration_only": True,
            "future_outcomes_used_in_live_decisions": False,
            "production_confidence_changed": False,
            "automatic_promotion": False,
        },
    }


def promotion_readiness(store: MicrostructureStore, instrument: str = "ES", *, min_labeled: int | None = None,
                        min_accuracy_pct: float | None = None, min_coverage_pct: float | None = None) -> dict[str, Any]:
    min_labeled = int(min_labeled or os.getenv("MICROSTRUCTURE_PROMOTION_MIN_LABELED", "100"))
    min_accuracy_pct = float(min_accuracy_pct or os.getenv("MICROSTRUCTURE_PROMOTION_MIN_ACCURACY_PCT", "55"))
    min_coverage_pct = float(min_coverage_pct or os.getenv("MICROSTRUCTURE_PROMOTION_MIN_COVERAGE_PCT", "95"))
    integrity = integrity_report(store, instrument, limit=max(1000, min_labeled * 3))
    calibration = calibration_report(store, instrument, limit=max(5000, min_labeled * 5))
    delta_metric = calibration["metrics"]["delta_direction"]
    depth_metric = calibration["metrics"]["depth_imbalance_direction"]
    best_accuracy = max([x for x in (delta_metric.get("accuracy_pct"), depth_metric.get("accuracy_pct")) if x is not None], default=None)
    gates = {
        "minimum_labeled_sample": calibration["labeled_samples"] >= min_labeled,
        "l2_coverage": integrity["l2_coverage_pct"] >= min_coverage_pct,
        "true_delta_coverage": integrity["true_delta_coverage_pct"] >= min_coverage_pct,
        "timestamp_integrity": bool(integrity["timestamp_monotonic"]),
        "predictive_accuracy": bool(best_accuracy is not None and best_accuracy >= min_accuracy_pct),
    }
    eligible = all(gates.values())
    approved_flag = _bool_env("MICROSTRUCTURE_PROMOTION_APPROVED", False)
    return {
        "ok": True,
        "status": "ELIGIBLE_FOR_REVIEW" if eligible else "COLLECTING",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "instrument": instrument.upper(),
        "thresholds": {"min_labeled": min_labeled, "min_accuracy_pct": min_accuracy_pct, "min_coverage_pct": min_coverage_pct},
        "gates": gates,
        "failed_gates": [k for k, v in gates.items() if not v],
        "best_observed_accuracy_pct": best_accuracy,
        "eligible_for_human_review": eligible,
        "operator_approval_flag": approved_flag,
        "production_promotion_applied": False,
        "required_next_stage": "HUMAN_REVIEW" if eligible else "COLLECT_MORE_REAL_DEPTH_AND_OUTCOMES",
        "governance": {
            "automatic_promotion": False,
            "operator_approval_alone_is_not_activation": True,
            "production_effect": "NONE",
            "influences_decision": False,
            "execution_authority": False,
        },
    }


def shadow_confirmation(analysis: Mapping[str, Any] | None, calibration: Mapping[str, Any] | None = None) -> dict[str, Any]:
    analysis = analysis or {}
    calibration = calibration or {}
    book = analysis.get("book") if isinstance(analysis.get("book"), Mapping) else {}
    execution = analysis.get("execution") if isinstance(analysis.get("execution"), Mapping) else {}
    interaction = analysis.get("interaction") if isinstance(analysis.get("interaction"), Mapping) else {}
    imbalance = _f(book.get("depth_imbalance"))
    delta = _f(execution.get("delta"))

    votes: list[float] = []
    evidence: list[str] = []
    if imbalance is not None and abs(imbalance) >= 0.05:
        votes.append(max(-1.0, min(1.0, imbalance)))
        evidence.append("DEPTH_IMBALANCE")
    if delta is not None and delta != 0:
        # bounded sign vote; magnitude is intentionally not normalized across providers yet.
        votes.append(1.0 if delta > 0 else -1.0)
        evidence.append("AGGRESSOR_DELTA")
    absorption = interaction.get("absorption_candidate") if isinstance(interaction.get("absorption_candidate"), Mapping) else {}
    if absorption.get("detected"):
        if absorption.get("side") == "ASK_SELLER":
            votes.append(-1.0); evidence.append("ASK_ABSORPTION")
        elif absorption.get("side") == "BID_BUYER":
            votes.append(1.0); evidence.append("BID_ABSORPTION")

    raw = sum(votes) / len(votes) if votes else 0.0
    score = round(50.0 + 50.0 * raw, 2) if votes else None
    direction = "BULLISH" if raw >= 0.15 else ("BEARISH" if raw <= -0.15 else "NEUTRAL")
    return {
        "eligible": bool(votes),
        "score": score,
        "direction": direction if votes else "UNAVAILABLE",
        "evidence": evidence,
        "calibrated_for_production": False,
        "calibration_labeled_samples": calibration.get("labeled_samples"),
        "governance": {"shadow_only": True, "influences_decision": False, "production_effect": "NONE", "execution_authority": False},
    }
