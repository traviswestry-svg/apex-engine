"""APEX 10 Sprint 5 — leakage-safe learning and confidence calibration.

This module scores settled outcomes, measures confidence calibration, and creates
bounded policy proposals.  It never mutates live decision logic automatically.
All fitting/evaluation uses session-disjoint chronological splits.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
import threading
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import feature_store_db

LEARNING_VERSION = "10.0.0_LEARNING_CALIBRATION"
MIN_TRAIN_SAMPLES = 100
MIN_EVAL_SAMPLES = 50
MAX_WEIGHT_DELTA = 0.10
MIN_BRIER_IMPROVEMENT = 0.005
_DB_PATH = os.getenv("DB_PATH", "apex_tracking.db")
_LOCK = threading.Lock()

SUCCESS_OUTCOMES = {"TARGET_FIRST", "TARGET_ONLY"}
FAILURE_OUTCOMES = {"STOP_FIRST", "STOP_ONLY"}


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _finite(v: Any) -> Optional[float]:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def init_learning_db() -> bool:
    try:
        with _conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS calibration_policies (
                policy_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                train_start TEXT,
                train_end TEXT,
                eval_start TEXT,
                eval_end TEXT,
                sample_counts_json TEXT NOT NULL,
                baseline_metrics_json TEXT NOT NULL,
                proposed_metrics_json TEXT NOT NULL,
                parameters_json TEXT NOT NULL,
                guardrails_json TEXT NOT NULL,
                promoted_at TEXT,
                promotion_note TEXT
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_cp_status ON calibration_policies(status)")
            c.commit()
        return True
    except Exception:
        return False


def outcome_to_binary(labels: Mapping[str, Any]) -> Optional[int]:
    outcome = str((labels or {}).get("final_outcome") or "").upper()
    if outcome in SUCCESS_OUTCOMES:
        return 1
    if outcome in FAILURE_OUTCOMES:
        return 0
    return None


def confidence_from_features(features: Mapping[str, Any]) -> Optional[float]:
    for key in ("effective_confidence", "confidence", "ici", "cluster_directional_confidence_adjusted"):
        v = _finite((features or {}).get(key))
        if v is not None:
            return _clamp(v / 100.0)
    return None


def brier_score(rows: Sequence[Mapping[str, Any]], transform=None) -> Optional[float]:
    vals: List[float] = []
    for row in rows:
        p = confidence_from_features(row.get("features") or {})
        y = outcome_to_binary(row.get("labels") or {})
        if p is None or y is None:
            continue
        if transform:
            p = _clamp(float(transform(p)))
        vals.append((p - y) ** 2)
    return round(sum(vals) / len(vals), 6) if vals else None


def calibration_report(rows: Sequence[Mapping[str, Any]], bins: int = 10) -> Dict[str, Any]:
    buckets: List[List[Tuple[float, int]]] = [[] for _ in range(max(2, min(int(bins), 20)))]
    usable = 0
    for row in rows:
        p = confidence_from_features(row.get("features") or {})
        y = outcome_to_binary(row.get("labels") or {})
        if p is None or y is None:
            continue
        usable += 1
        idx = min(len(buckets) - 1, int(p * len(buckets)))
        buckets[idx].append((p, y))
    out = []
    ece = 0.0
    for i, vals in enumerate(buckets):
        if not vals:
            continue
        avg_p = sum(v[0] for v in vals) / len(vals)
        hit = sum(v[1] for v in vals) / len(vals)
        ece += (len(vals) / max(1, usable)) * abs(avg_p - hit)
        out.append({"bin": i, "n": len(vals), "mean_confidence": round(avg_p * 100, 2),
                    "observed_success_rate": round(hit * 100, 2),
                    "calibration_gap_points": round((avg_p - hit) * 100, 2)})
    return {"sample_count": usable, "brier_score": brier_score(rows),
            "expected_calibration_error": round(ece, 6), "bins": out}


def _fit_affine(rows: Sequence[Mapping[str, Any]]) -> Dict[str, float]:
    pairs: List[Tuple[float, int]] = []
    for row in rows:
        p = confidence_from_features(row.get("features") or {})
        y = outcome_to_binary(row.get("labels") or {})
        if p is not None and y is not None:
            pairs.append((p, y))
    if len(pairs) < 2:
        return {"slope": 1.0, "intercept": 0.0}
    mx = sum(p for p, _ in pairs) / len(pairs)
    my = sum(y for _, y in pairs) / len(pairs)
    var = sum((p - mx) ** 2 for p, _ in pairs)
    slope = 1.0 if var <= 1e-12 else sum((p - mx) * (y - my) for p, y in pairs) / var
    intercept = my - slope * mx
    # Bounded movement prevents a noisy fit from rewriting confidence semantics.
    slope = max(1.0 - MAX_WEIGHT_DELTA, min(1.0 + MAX_WEIGHT_DELTA, slope))
    intercept = max(-MAX_WEIGHT_DELTA, min(MAX_WEIGHT_DELTA, intercept))
    return {"slope": round(slope, 6), "intercept": round(intercept, 6)}


def _apply(params: Mapping[str, float]):
    return lambda p: _clamp(float(params["intercept"]) + float(params["slope"]) * p)


def _all_pairs() -> List[Dict[str, Any]]:
    sessions = feature_store_db.sessions("features")
    if not sessions:
        return []
    # Deliberately use the protected loader and a chronological dummy eval tail.
    if len(sessions) == 1:
        return []
    split = max(1, len(sessions) - 1)
    data = feature_store_db.load_training_pairs(train_sessions=sessions[:split], eval_sessions=sessions[split:])
    return list(data["train"]) + list(data["eval"])


def build_policy_proposal(*, train_sessions: Sequence[str], eval_sessions: Sequence[str]) -> Dict[str, Any]:
    pairs = feature_store_db.load_training_pairs(train_sessions=train_sessions, eval_sessions=eval_sessions)
    train, eval_rows = pairs["train"], pairs["eval"]
    train_usable = calibration_report(train)["sample_count"]
    eval_usable = calibration_report(eval_rows)["sample_count"]
    params = _fit_affine(train)
    baseline = brier_score(eval_rows)
    proposed = brier_score(eval_rows, _apply(params))
    improvement = None if baseline is None or proposed is None else round(baseline - proposed, 6)
    eligible = (train_usable >= MIN_TRAIN_SAMPLES and eval_usable >= MIN_EVAL_SAMPLES and
                improvement is not None and improvement >= MIN_BRIER_IMPROVEMENT)
    guardrails = {
        "chronological_session_split": True,
        "session_overlap_permitted": False,
        "automatic_activation": False,
        "minimum_train_samples": MIN_TRAIN_SAMPLES,
        "minimum_eval_samples": MIN_EVAL_SAMPLES,
        "maximum_parameter_delta": MAX_WEIGHT_DELTA,
        "minimum_eval_brier_improvement": MIN_BRIER_IMPROVEMENT,
        "promotion_eligible": eligible,
        "reasons": [] if eligible else [
            r for r in (
                None if train_usable >= MIN_TRAIN_SAMPLES else "insufficient training samples",
                None if eval_usable >= MIN_EVAL_SAMPLES else "insufficient evaluation samples",
                None if improvement is not None else "evaluation metric unavailable",
                None if improvement is not None and improvement >= MIN_BRIER_IMPROVEMENT else "out-of-sample improvement below threshold",
            ) if r
        ],
    }
    payload = {"version": LEARNING_VERSION, "train_sessions": list(train_sessions),
               "eval_sessions": list(eval_sessions), "parameters": params,
               "sample_counts": {"train": train_usable, "eval": eval_usable},
               "baseline_metrics": {"eval_brier": baseline},
               "proposed_metrics": {"eval_brier": proposed, "improvement": improvement},
               "guardrails": guardrails}
    policy_id = "cal_" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    payload["policy_id"] = policy_id
    return payload


def persist_proposal(proposal: Mapping[str, Any]) -> bool:
    if not init_learning_db():
        return False
    try:
        with _LOCK, _conn() as c:
            c.execute("""INSERT OR IGNORE INTO calibration_policies
                (policy_id,created_at,status,train_start,train_end,eval_start,eval_end,
                 sample_counts_json,baseline_metrics_json,proposed_metrics_json,
                 parameters_json,guardrails_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (proposal["policy_id"], _now(), "PROPOSED",
                 (proposal.get("train_sessions") or [None])[0], (proposal.get("train_sessions") or [None])[-1],
                 (proposal.get("eval_sessions") or [None])[0], (proposal.get("eval_sessions") or [None])[-1],
                 json.dumps(proposal.get("sample_counts") or {}), json.dumps(proposal.get("baseline_metrics") or {}),
                 json.dumps(proposal.get("proposed_metrics") or {}), json.dumps(proposal.get("parameters") or {}),
                 json.dumps(proposal.get("guardrails") or {})))
            c.commit()
        return True
    except Exception:
        return False


def promote_policy(policy_id: str, note: str = "") -> Dict[str, Any]:
    """Promote only an eligible persisted proposal; never auto-called."""
    if not init_learning_db():
        return {"ok": False, "reason": "learning store unavailable"}
    with _LOCK, _conn() as c:
        row = c.execute("SELECT * FROM calibration_policies WHERE policy_id=?", (policy_id,)).fetchone()
        if not row:
            return {"ok": False, "reason": "policy not found"}
        guards = json.loads(row["guardrails_json"])
        if not guards.get("promotion_eligible"):
            return {"ok": False, "reason": "proposal failed promotion guardrails", "guardrails": guards}
        c.execute("UPDATE calibration_policies SET status='RETIRED' WHERE status='ACTIVE'")
        c.execute("UPDATE calibration_policies SET status='ACTIVE', promoted_at=?, promotion_note=? WHERE policy_id=?",
                  (_now(), note, policy_id))
        c.commit()
    return {"ok": True, "policy_id": policy_id, "status": "ACTIVE"}


def active_policy() -> Optional[Dict[str, Any]]:
    if not init_learning_db():
        return None
    with _conn() as c:
        r = c.execute("SELECT * FROM calibration_policies WHERE status='ACTIVE' ORDER BY promoted_at DESC LIMIT 1").fetchone()
    if not r:
        return None
    return {"policy_id": r["policy_id"], "status": r["status"],
            "parameters": json.loads(r["parameters_json"]), "promoted_at": r["promoted_at"]}


def apply_active_calibration(confidence: Any) -> Dict[str, Any]:
    raw = _finite(confidence)
    if raw is None:
        return {"available": False, "raw_confidence": None, "calibrated_confidence": None}
    policy = active_policy()
    if not policy:
        return {"available": True, "raw_confidence": round(raw, 2),
                "calibrated_confidence": round(raw, 2), "policy_applied": False}
    p = _apply(policy["parameters"])(_clamp(raw / 100.0)) * 100.0
    return {"available": True, "raw_confidence": round(raw, 2),
            "calibrated_confidence": round(p, 2), "policy_applied": True,
            "policy_id": policy["policy_id"], "parameters": policy["parameters"]}
