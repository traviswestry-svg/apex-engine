"""APEX 18.0.7 — Adaptive Refusal Calibration.

Uses graded refusal replay outcomes to recommend bounded, explainable changes to
premium eligibility policy. Recommendations are inert until explicitly promoted.
No broker action is possible from this module.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

VERSION = "18.0.7_ADAPTIVE_REFUSAL_CALIBRATION"
DEFAULT_WEIGHTS = {
    "AUCTION": 0.20,
    "REGIME": 0.20,
    "GAMMA": 0.15,
    "FLOW": 0.15,
    "VOL": 0.10,
    "QUALITY": 0.20,
}
DEFAULT_THRESHOLD = 65.0
PROTECTED = {"AVOIDED_LOSS", "AVOIDED_STOP"}
MISSED = {"MISSED_WIN", "FALSE_REJECTION"}
ACTIONABLE = PROTECTED | MISSED


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return default if value is None else float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    clean = {k: _clamp(_f(weights.get(k), DEFAULT_WEIGHTS[k]), 0.05, 0.40) for k in DEFAULT_WEIGHTS}
    total = sum(clean.values()) or 1.0
    return {k: round(v / total, 4) for k, v in clean.items()}


class CalibrationStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("DB_PATH", "apex_tracking.db")
        self._init()

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        directory = os.path.dirname(self.db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with self._connect() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS premium_calibration_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                sample_size INTEGER NOT NULL,
                protected_count INTEGER NOT NULL,
                missed_count INTEGER NOT NULL,
                source_policy_json TEXT NOT NULL,
                recommendation_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                promoted_at TEXT,
                promoted_by TEXT
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS premium_calibration_active (
                singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
                policy_json TEXT NOT NULL,
                source_run_id INTEGER,
                promoted_at TEXT NOT NULL,
                promoted_by TEXT NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_pcr_created ON premium_calibration_runs(created_at)")
            c.commit()

    def active_policy(self) -> Dict[str, Any]:
        with self._connect() as c:
            row = c.execute("SELECT * FROM premium_calibration_active WHERE singleton_id=1").fetchone()
        if not row:
            return {
                "version": VERSION,
                "threshold": _f(os.getenv("PREMIUM_ELIGIBILITY_THRESHOLD"), DEFAULT_THRESHOLD),
                "weights": dict(DEFAULT_WEIGHTS),
                "source": "DEFAULT_GOVERNED_POLICY",
                "source_run_id": None,
                "promoted_at": None,
            }
        policy = json.loads(row["policy_json"] or "{}")
        policy.update({"source": "PROMOTED_CALIBRATION", "source_run_id": row["source_run_id"],
                       "promoted_at": row["promoted_at"], "promoted_by": row["promoted_by"]})
        return policy

    def _graded_rows(self, lookback: int) -> List[sqlite3.Row]:
        with self._connect() as c:
            exists = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='premium_discipline_decisions'").fetchone()
            if not exists:
                return []
            return c.execute(
                "SELECT id, strategy, eligibility_score, threshold, decision_json, "
                "counterfactual_outcome, counterfactual_pnl, graded_at "
                "FROM premium_discipline_decisions WHERE decision='REFUSE' "
                "AND counterfactual_outcome IS NOT NULL ORDER BY id DESC LIMIT ?",
                (max(1, min(int(lookback), 5000)),),
            ).fetchall()

    def run(self, *, min_sample: int = 20, lookback: int = 500) -> Dict[str, Any]:
        active = self.active_policy()
        rows = self._graded_rows(lookback)
        actionable = [r for r in rows if r["counterfactual_outcome"] in ACTIONABLE]
        protected = [r for r in actionable if r["counterfactual_outcome"] in PROTECTED]
        missed = [r for r in actionable if r["counterfactual_outcome"] in MISSED]
        sample = len(actionable)

        evidence: Dict[str, Any] = {
            "graded_rows_considered": len(rows), "actionable_sample": sample,
            "protected": len(protected), "missed_winners": len(missed),
            "refusal_precision_pct": round(100 * len(protected) / sample, 1) if sample else None,
            "minimum_sample": int(min_sample), "lookback": int(lookback),
            "factor_separation": {},
        }
        source_weights = _normalize_weights(active.get("weights") or DEFAULT_WEIGHTS)
        source_threshold = _clamp(_f(active.get("threshold"), DEFAULT_THRESHOLD), 55.0, 80.0)
        recommended_weights = dict(source_weights)
        recommended_threshold = source_threshold
        reasons: List[str] = []
        status = "INSUFFICIENT_DATA"

        if sample >= min_sample:
            precision = len(protected) / sample
            # Bounded threshold adjustment. High false-rejection rate lowers the
            # gate; high protection precision raises it slightly. One run can
            # never move the threshold by more than three points.
            if precision < 0.55:
                delta = -3.0
                reasons.append("False rejections dominate the replay sample; lower the gate modestly.")
            elif precision < 0.65:
                delta = -1.5
                reasons.append("Refusal precision is below target; reduce over-filtering.")
            elif precision > 0.85:
                delta = 2.0
                reasons.append("Refusals are highly protective; modestly strengthen selectivity.")
            elif precision > 0.75:
                delta = 1.0
                reasons.append("Refusal precision is strong; slightly strengthen selectivity.")
            else:
                delta = 0.0
                reasons.append("Refusal precision is balanced; retain the current threshold.")
            recommended_threshold = round(_clamp(source_threshold + delta, 55.0, 80.0), 1)

            def factor_means(group: List[sqlite3.Row]) -> Dict[str, float]:
                buckets: Dict[str, List[float]] = {k: [] for k in DEFAULT_WEIGHTS}
                for row in group:
                    try:
                        decision = json.loads(row["decision_json"] or "{}")
                    except Exception:
                        decision = {}
                    for factor in decision.get("factors") or []:
                        code = str(factor.get("code") or "").upper()
                        if code in buckets:
                            buckets[code].append(_f(factor.get("score")))
                return {k: (sum(v) / len(v) if v else 0.0) for k, v in buckets.items()}

            pmeans, mmeans = factor_means(protected), factor_means(missed)
            adjusted: Dict[str, float] = {}
            for code, base in source_weights.items():
                separation = pmeans.get(code, 0.0) - mmeans.get(code, 0.0)
                evidence["factor_separation"][code] = {
                    "protected_mean": round(pmeans.get(code, 0.0), 2),
                    "missed_mean": round(mmeans.get(code, 0.0), 2),
                    "separation": round(separation, 2),
                }
                # Reward factors whose low scores distinguish protected refusals
                # from missed winners; trim factors showing reversed separation.
                multiplier = _clamp(1.0 - separation / 200.0, 0.90, 1.10)
                adjusted[code] = base * multiplier
            recommended_weights = _normalize_weights(adjusted)
            status = "RECOMMENDED"
        else:
            reasons.append(f"At least {min_sample} actionable replay outcomes are required before calibration.")

        recommendation = {
            "version": VERSION,
            "status": status,
            "threshold": recommended_threshold,
            "weights": recommended_weights,
            "changes": {
                "threshold_delta": round(recommended_threshold - source_threshold, 1),
                "weight_deltas": {k: round(recommended_weights[k] - source_weights[k], 4) for k in DEFAULT_WEIGHTS},
            },
            "reasons": reasons,
            "operational": False,
            "requires_explicit_promotion": True,
        }
        fingerprint = hashlib.sha256(json.dumps({"source": active, "recommendation": recommendation,
                                                   "evidence": evidence}, sort_keys=True, default=str).encode()).hexdigest()[:24]
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as c:
            c.execute("""INSERT OR IGNORE INTO premium_calibration_runs
                (fingerprint, created_at, status, sample_size, protected_count, missed_count,
                 source_policy_json, recommendation_json, evidence_json)
                 VALUES (?,?,?,?,?,?,?,?,?)""",
                (fingerprint, now, status, sample, len(protected), len(missed),
                 json.dumps(active, sort_keys=True), json.dumps(recommendation, sort_keys=True),
                 json.dumps(evidence, sort_keys=True)))
            c.commit()
            row = c.execute("SELECT id, created_at FROM premium_calibration_runs WHERE fingerprint=?", (fingerprint,)).fetchone()
        return {"run_id": row["id"], "created_at": row["created_at"], "recommendation": recommendation,
                "evidence": evidence, "active_policy": active}

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._connect() as c:
            rows = c.execute("SELECT * FROM premium_calibration_runs ORDER BY id DESC LIMIT ?",
                             (max(1, min(int(limit), 200)),)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for field in ("source_policy_json", "recommendation_json", "evidence_json"):
                item[field[:-5]] = json.loads(item.pop(field) or "{}")
            result.append(item)
        return result

    def promote(self, run_id: int, *, promoted_by: str = "operator") -> Dict[str, Any]:
        with self._connect() as c:
            row = c.execute("SELECT * FROM premium_calibration_runs WHERE id=?", (int(run_id),)).fetchone()
            if not row:
                raise ValueError("Calibration run not found.")
            recommendation = json.loads(row["recommendation_json"] or "{}")
            if recommendation.get("status") != "RECOMMENDED":
                raise ValueError("Only a recommendation with sufficient evidence can be promoted.")
            policy = {
                "version": VERSION,
                "threshold": _clamp(_f(recommendation.get("threshold"), DEFAULT_THRESHOLD), 55.0, 80.0),
                "weights": _normalize_weights(recommendation.get("weights") or DEFAULT_WEIGHTS),
            }
            now = datetime.now(timezone.utc).isoformat()
            c.execute("""INSERT INTO premium_calibration_active
                (singleton_id, policy_json, source_run_id, promoted_at, promoted_by)
                VALUES (1,?,?,?,?) ON CONFLICT(singleton_id) DO UPDATE SET
                policy_json=excluded.policy_json, source_run_id=excluded.source_run_id,
                promoted_at=excluded.promoted_at, promoted_by=excluded.promoted_by""",
                (json.dumps(policy, sort_keys=True), int(run_id), now, promoted_by))
            c.execute("UPDATE premium_calibration_runs SET promoted_at=?, promoted_by=? WHERE id=?",
                      (now, promoted_by, int(run_id)))
            c.commit()
        return {"promoted": True, "run_id": int(run_id), "policy": policy,
                "promoted_at": now, "promoted_by": promoted_by}
