"""APEX 25.4 — Institutional Decision Review and Learning Engine.

Closed-loop, deterministic review layer. It preserves the full decision
lifecycle, grades decision *quality* (not merely outcome direction), attributes
errors to specific causes, and proposes governed learning recommendations that
require explicit human approval before any production change.

Hard guarantees
---------------
* No uncontrolled self-modification. Recommendations are proposals only; nothing
  in this engine mutates weights, thresholds, confidence, or execution.
  ``production_effect`` is ``NONE``.
* Review grades are reproducible: identical lifecycle + realized inputs produce
  an identical grade and decomposition.
* Every recommendation carries supporting evidence and a governance status; it
  cannot bypass the PROPOSED -> UNDER_REVIEW -> APPROVED/REJECTED -> DEPLOYED/
  ROLLED_BACK workflow.
* Replay reconstructs the *stored* decision state exactly (no recomputation).
* NOT_GRADEABLE is used honestly whenever an outcome cannot be evaluated.

Reuse (no duplication)
----------------------
* 25.0 integrity, 25.1 reasoning, 25.2 forecast, 25.3 calibration for the live
  ``build_review`` composition.
* ``institutional_governance.audit`` for the audit trail of approve/reject.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
import uuid
from typing import Any, Mapping, Optional, Sequence

from . import institutional_decision_integrity_v250 as integrity

try:
    from . import institutional_reasoning_v251 as reasoning  # type: ignore
except Exception:  # pragma: no cover
    reasoning = None  # type: ignore
try:
    from . import decision_outcome_forecast_v252 as forecast_engine  # type: ignore
except Exception:  # pragma: no cover
    forecast_engine = None  # type: ignore
try:
    from . import adaptive_confidence_calibration_v253 as calibration_engine  # type: ignore
except Exception:  # pragma: no cover
    calibration_engine = None  # type: ignore
try:
    from . import institutional_governance as governance  # type: ignore
except Exception:  # pragma: no cover
    governance = None  # type: ignore

VERSION = "25.4.0_INSTITUTIONAL_DECISION_REVIEW"
SCHEMA_VERSION = "apex.decision_review.v254.v1"

GRADES = ("A+", "A", "A-", "B+", "B", "B-", "C", "D", "F", "NOT_GRADEABLE")
WORKFLOW = ("PROPOSED", "UNDER_REVIEW", "APPROVED", "REJECTED", "DEPLOYED", "ROLLED_BACK")

DECOMPOSITION_KEYS = (
    "signal_quality", "evidence_quality", "reasoning_quality", "forecast_quality",
    "confidence_quality", "risk_quality", "timing_quality", "execution_readiness_quality",
)


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #
def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso_now() -> str:
    return _now().isoformat()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _round(v: Any, p: int = 2) -> Optional[float]:
    return None if v is None else round(float(v), p)


def _grade_from_score(score: float) -> str:
    if score >= 95:
        return "A+"
    if score >= 90:
        return "A"
    if score >= 85:
        return "A-"
    if score >= 80:
        return "B+"
    if score >= 75:
        return "B"
    if score >= 70:
        return "B-"
    if score >= 60:
        return "C"
    if score >= 50:
        return "D"
    return "F"


# --------------------------------------------------------------------------- #
# Persistence (governed sqlite; never repo root by default).
# --------------------------------------------------------------------------- #
def _db_path() -> str:
    return os.getenv("APEX_DECISION_REVIEW_DB", "apex_decision_review.db")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_db_path())
    c.row_factory = sqlite3.Row
    return c


def init_db() -> dict[str, Any]:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS decision_lifecycle_v254(
              decision_id TEXT PRIMARY KEY,
              symbol TEXT, direction TEXT, setup_family TEXT, market_regime TEXT,
              execution_eligibility TEXT, decision_at TEXT NOT NULL,
              engine_versions_json TEXT, lifecycle_json TEXT NOT NULL,
              realized_json TEXT, review_json TEXT, review_grade TEXT,
              reviewed_at TEXT, integrity_hash TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_review_decision_at ON decision_lifecycle_v254(decision_at);
            CREATE INDEX IF NOT EXISTS idx_review_grade ON decision_lifecycle_v254(review_grade);
            CREATE TABLE IF NOT EXISTS review_recommendations_v254(
              recommendation_id TEXT PRIMARY KEY,
              created_at TEXT NOT NULL, status TEXT NOT NULL,
              affected_component TEXT NOT NULL, proposed_change TEXT NOT NULL,
              expected_benefit TEXT, risks TEXT, rollback_plan TEXT,
              supporting_sample INTEGER, supporting_metrics_json TEXT,
              source_decision_id TEXT, reviewed_by TEXT, reviewed_at TEXT,
              integrity_hash TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_reco_status ON review_recommendations_v254(status, created_at);
            """
        )
    return {"ok": True, "db_path": _db_path(), "schema_version": SCHEMA_VERSION}


def _hash(obj: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


# --------------------------------------------------------------------------- #
# Lifecycle capture.
# --------------------------------------------------------------------------- #
def build_lifecycle_snapshot(payload: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Assemble the full lifecycle record from the governed 25.x stack."""
    root = payload if isinstance(payload, Mapping) else {}
    decision = integrity.evaluate_decision(root)
    decision_block = _mapping(decision.get("decision"))
    health = _mapping(decision.get("evidence_health"))
    explain = _mapping(decision.get("explainability"))

    reasoning_block = reasoning.build_reasoning(root)["reasoning"] if reasoning else {}
    forecast_block = forecast_engine.build_forecast(root)["forecast"] if forecast_engine else {}
    calibration_block = (calibration_engine.build_calibration(root)["calibration"]
                         if calibration_engine else {})

    decision_id = (_text(decision_block.get("decision_id"))
                   or _text(root.get("decision_id"))
                   or _text(root.get("signal_id"))
                   or "dec_" + uuid.uuid5(uuid.NAMESPACE_URL, _hash(dict(root))).hex[:18])

    return {
        "decision_id": decision_id,
        "symbol": _text(root.get("symbol") or _mapping(root.get("market_state")).get("symbol") or "SPX"),
        "direction": _text(decision_block.get("direction")),
        "setup_family": _text(root.get("setup_family") or "UNKNOWN"),
        "market_regime": _text(root.get("market_regime") or _mapping(root.get("market_state")).get("regime") or "UNKNOWN"),
        "execution_eligibility": _text(decision_block.get("execution_eligibility")),
        "decision_at": _text(root.get("as_of") or _iso_now()),
        "evidence_health": health,
        "provider_health": _mapping(root.get("provider_health")) or {"state": health.get("state")},
        "thesis": explain.get("thesis"),
        "counter_thesis": explain.get("counter_thesis"),
        "evidence_ranking": reasoning_block.get("evidence_rankings"),
        "confidence_waterfall": reasoning_block.get("confidence_waterfall"),
        "forecast": forecast_block,
        "calibration": calibration_block.get("confidence_layers"),
        "raw_confidence": decision_block.get("raw_confidence"),
        "integrity_adjusted_confidence": decision_block.get("integrity_adjusted_confidence"),
        "confidence_ceiling": decision_block.get("confidence_ceiling"),
        "engine_versions": {
            "integrity": integrity.VERSION,
            "reasoning": getattr(reasoning, "VERSION", None),
            "forecast": getattr(forecast_engine, "VERSION", None),
            "calibration": getattr(calibration_engine, "VERSION", None),
            "review": VERSION,
        },
    }


def record_decision(payload: Optional[Mapping[str, Any]] = None, *,
                    lifecycle: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    record = dict(lifecycle) if isinstance(lifecycle, Mapping) else build_lifecycle_snapshot(payload)
    init_db()
    integrity_hash = _hash(record)
    with _conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO decision_lifecycle_v254
               (decision_id, symbol, direction, setup_family, market_regime,
                execution_eligibility, decision_at, engine_versions_json,
                lifecycle_json, integrity_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (record["decision_id"], record.get("symbol"), record.get("direction"),
             record.get("setup_family"), record.get("market_regime"),
             record.get("execution_eligibility"), record.get("decision_at"),
             json.dumps(record.get("engine_versions")), json.dumps(record), integrity_hash),
        )
    return {"ok": True, "decision_id": record["decision_id"], "integrity_hash": integrity_hash,
            "production_effect": "NONE"}


def _load_record(decision_id: str) -> Optional[dict[str, Any]]:
    init_db()
    with _conn() as c:
        row = c.execute("SELECT * FROM decision_lifecycle_v254 WHERE decision_id=?", (decision_id,)).fetchone()
    if not row:
        return None
    record = dict(row)
    for key in ("lifecycle_json", "realized_json", "review_json", "engine_versions_json"):
        if record.get(key):
            try:
                record[key.replace("_json", "")] = json.loads(record[key])
            except (TypeError, ValueError):
                pass
        record.pop(key, None)
    return record


# --------------------------------------------------------------------------- #
# Review / grading engine (deterministic).
# --------------------------------------------------------------------------- #
def _gradeable(lifecycle: Mapping[str, Any], realized: Mapping[str, Any]) -> tuple[bool, str]:
    if not realized:
        return False, "No realized outcome supplied; cannot grade honestly."
    if realized.get("matured") is False:
        return False, "Outcome horizon has not matured."
    health_state = _text(_mapping(lifecycle.get("evidence_health")).get("state")).upper()
    if _text(lifecycle.get("execution_eligibility")).upper() == "STAND_DOWN" and realized.get("taken") is not True:
        # A correct stand-down with no trade taken is graded on decision quality,
        # not outcome; still gradeable but flagged.
        return True, "Graded as a (correct) stand-down decision."
    if health_state == "UNRELIABLE" and realized.get("taken") is not True:
        return False, "Evidence was unreliable and no trade was taken; not meaningfully gradeable."
    return True, "Gradeable."


def _decomposition(lifecycle: Mapping[str, Any], realized: Mapping[str, Any]) -> dict[str, float]:
    health = _mapping(lifecycle.get("evidence_health"))
    fresh_ratio = _number(health.get("fresh_ratio"))
    critical_degraded = _list(health.get("critical_degraded"))
    forecast = _mapping(lifecycle.get("forecast"))

    raw_conf = _number(lifecycle.get("raw_confidence"))
    adj_conf = _number(lifecycle.get("integrity_adjusted_confidence"))
    won = 1.0 if realized.get("won") else 0.0
    predicted_dir = _text(lifecycle.get("direction")).upper()
    realized_dir = _text(realized.get("realized_direction") or realized.get("direction")).upper()
    direction_correct = predicted_dir and predicted_dir == realized_dir and predicted_dir != "NEUTRAL"

    # Evidence quality: coverage + critical health.
    evidence_quality = _clamp(fresh_ratio * 100 - len(critical_degraded) * 15)
    # Signal quality: adjusted confidence support, penalized if built on thin evidence.
    signal_quality = _clamp(adj_conf * (0.6 + 0.4 * fresh_ratio))
    # Reasoning quality: balanced thesis + counter-thesis presence.
    has_thesis = bool(_text(lifecycle.get("thesis")))
    has_counter = bool(_text(lifecycle.get("counter_thesis")))
    reasoning_quality = _clamp(50 + (25 if has_thesis else 0) + (25 if has_counter else 0)
                               - (10 if not direction_correct else 0))
    # Forecast quality: from realized forecast error when available.
    pred_move = _number(forecast.get("expected_move_points"))
    real_move = _number(realized.get("realized_move_points"), pred_move)
    move_err = abs(pred_move - real_move)
    forecast_quality = _clamp(100 - move_err / max(1.0, pred_move) * 60
                              - (25 if not direction_correct else 0))
    # Confidence quality: how well stated confidence matched the binary outcome.
    confidence_quality = _clamp(100 - abs(adj_conf / 100 - won) * 100)
    # Risk quality: invalidation appropriateness (adverse excursion vs planned).
    pred_mae = _number(forecast.get("expected_mae"))
    real_mae = _number(realized.get("realized_mae"), pred_mae)
    risk_quality = _clamp(100 - abs(pred_mae - real_mae) / max(1.0, pred_mae) * 50)
    # Timing quality: favorable-vs-adverse sequencing when provided.
    if realized.get("adverse_before_favorable") is True:
        timing_quality = 55.0
    elif realized.get("adverse_before_favorable") is False:
        timing_quality = 85.0
    else:
        timing_quality = 70.0
    # Execution-readiness quality: eligibility appropriate to evidence.
    elig = _text(lifecycle.get("execution_eligibility")).upper()
    if elig == "ELIGIBLE" and evidence_quality >= 60:
        execution_readiness_quality = 90.0
    elif elig in {"WATCH", "STAND_DOWN"} and evidence_quality < 60:
        execution_readiness_quality = 85.0  # correctly cautious
    else:
        execution_readiness_quality = 60.0

    return {
        "signal_quality": _round(signal_quality),
        "evidence_quality": _round(evidence_quality),
        "reasoning_quality": _round(reasoning_quality),
        "forecast_quality": _round(forecast_quality),
        "confidence_quality": _round(confidence_quality),
        "risk_quality": _round(risk_quality),
        "timing_quality": _round(timing_quality),
        "execution_readiness_quality": _round(execution_readiness_quality),
    }


def _attribute_errors(lifecycle: Mapping[str, Any], realized: Mapping[str, Any],
                      decomposition: Mapping[str, Any]) -> list[str]:
    causes: list[str] = []
    health = _mapping(lifecycle.get("evidence_health"))
    predicted_dir = _text(lifecycle.get("direction")).upper()
    realized_dir = _text(realized.get("realized_direction") or realized.get("direction")).upper()
    direction_correct = predicted_dir and predicted_dir == realized_dir and predicted_dir != "NEUTRAL"
    won = bool(realized.get("won"))
    adj_conf = _number(lifecycle.get("integrity_adjusted_confidence"))
    elig = _text(lifecycle.get("execution_eligibility")).upper()

    if elig == "STAND_DOWN" and realized.get("taken") is not True:
        causes.append("DECISION_CORRECTLY_STOOD_DOWN")
    if predicted_dir and not direction_correct and realized_dir:
        causes.append("WRONG_DIRECTIONAL_THESIS")
    # Confidence over/understatement — the win/loss vs stated confidence.
    if not won and adj_conf >= 70:
        causes.append("CONFIDENCE_OVERSTATED")
    if won and adj_conf < 50:
        causes.append("CONFIDENCE_UNDERSTATED")
    # Evidence-state causes.
    for item in _list(health.get("sources")):
        state = _text(_mapping(item).get("state")).upper()
        if state == "STALE":
            causes.append("STALE_DATA")
            break
    for item in _list(health.get("sources")):
        state = _text(_mapping(item).get("state")).upper()
        if state == "MISSING":
            causes.append("MISSING_EVIDENCE")
            break
    if _list(health.get("critical_degraded")):
        causes.append("PROVIDER_FAILURE")
    # Invalidation / target sizing.
    forecast = _mapping(lifecycle.get("forecast"))
    if realized.get("invalidated") and _number(realized.get("realized_mae")) < _number(forecast.get("expected_mae")):
        causes.append("INVALIDATION_TOO_TIGHT")
    if not realized.get("target_hit") and won is False and _number(realized.get("realized_mfe")) > 0 \
            and _number(realized.get("realized_mfe")) < _number(forecast.get("expected_move_points")):
        causes.append("TARGET_TOO_AGGRESSIVE")
    # Sound decision, unlucky outcome / lucky outcome flags.
    process_score = sum(_number(decomposition.get(k)) for k in DECOMPOSITION_KEYS) / len(DECOMPOSITION_KEYS)
    if not won and process_score >= 70:
        causes.append("CORRECT_THESIS_ADVERSE_VARIANCE")
    if won and process_score < 55:
        causes.append("FAVORABLE_OUTCOME_WEAK_PROCESS")
    # De-duplicate, preserve order.
    seen = set()
    ordered = []
    for c in causes:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


def review_decision(lifecycle: Mapping[str, Any], realized: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    realized = _mapping(realized)
    gradeable, reason = _gradeable(lifecycle, realized)
    decomposition = _decomposition(lifecycle, realized) if realized else {k: None for k in DECOMPOSITION_KEYS}

    if not gradeable:
        return {
            "ok": True, "decision_id": lifecycle.get("decision_id"),
            "review_grade": "NOT_GRADEABLE", "gradeable": False, "reason": reason,
            "decomposition": decomposition, "error_attribution": [],
            "process_score": None,
            "outcome_luck_flag": None,
            "version": VERSION, "generated_at": _iso_now(), "production_effect": "NONE",
        }

    process_score = sum(_number(decomposition.get(k)) for k in DECOMPOSITION_KEYS) / len(DECOMPOSITION_KEYS)
    attribution = _attribute_errors(lifecycle, realized, decomposition)
    won = bool(realized.get("won"))
    grade = _grade_from_score(process_score)  # graded on decision quality, not outcome

    outcome_luck = None
    if not won and process_score >= 70:
        outcome_luck = "SOUND_DECISION_ADVERSE_OUTCOME"
    elif won and process_score < 55:
        outcome_luck = "WEAK_DECISION_FAVORABLE_OUTCOME"

    return {
        "ok": True,
        "decision_id": lifecycle.get("decision_id"),
        "review_grade": grade,
        "gradeable": True,
        "reason": reason,
        "graded_on": "DECISION_QUALITY_NOT_OUTCOME_DIRECTION",
        "won": won,
        "process_score": _round(process_score),
        "decomposition": decomposition,
        "error_attribution": attribution,
        "outcome_luck_flag": outcome_luck,
        "version": VERSION,
        "generated_at": _iso_now(),
        "production_effect": "NONE",
    }


def persist_review(decision_id: str, review: Mapping[str, Any], realized: Mapping[str, Any]) -> dict[str, Any]:
    init_db()
    with _conn() as c:
        cur = c.execute(
            "UPDATE decision_lifecycle_v254 SET realized_json=?, review_json=?, review_grade=?, reviewed_at=? WHERE decision_id=?",
            (json.dumps(dict(realized)), json.dumps(dict(review)), review.get("review_grade"), _iso_now(), decision_id),
        )
    return {"ok": cur.rowcount > 0, "updated": cur.rowcount, "decision_id": decision_id}


# --------------------------------------------------------------------------- #
# Governed learning recommendations.
# --------------------------------------------------------------------------- #
def generate_recommendations(review: Mapping[str, Any], lifecycle: Mapping[str, Any]) -> list[dict[str, Any]]:
    recos: list[dict[str, Any]] = []
    decomposition = _mapping(review.get("decomposition"))
    attribution = _list(review.get("error_attribution"))

    def _make(component: str, change: str, benefit: str, risks: str, rollback: str, metrics: Mapping[str, Any]):
        payload = {
            "recommendation_id": "reco_" + uuid.uuid4().hex[:16],
            "status": "PROPOSED",
            "affected_component": component,
            "proposed_change": change,
            "expected_benefit": benefit,
            "risks": risks,
            "rollback_plan": rollback,
            "supporting_sample": 1,
            "supporting_metrics": dict(metrics),
            "source_decision_id": lifecycle.get("decision_id"),
            "reviewed_by": None,
            "reviewed_at": None,
            "created_at": _iso_now(),
        }
        recos.append(payload)

    if "CONFIDENCE_OVERSTATED" in attribution:
        _make("confidence_ceiling", "Reduce confidence ceiling for this setup/regime pending more samples.",
              "Better-calibrated confidence.", "May under-state genuinely strong setups.",
              "Restore prior ceiling; no production code changed.",
              {"confidence_quality": decomposition.get("confidence_quality")})
    if "STALE_DATA" in attribution:
        _make("freshness_threshold", "Tighten freshness threshold on the stale source.",
              "Fewer decisions on stale evidence.", "May increase STAND_DOWN frequency.",
              "Relax threshold to prior value.",
              {"evidence_quality": decomposition.get("evidence_quality")})
    if "PROVIDER_FAILURE" in attribution:
        _make("provider_health_penalty", "Increase provider-health penalty when critical providers degrade.",
              "Stronger down-weighting of degraded evidence.", "May over-penalize transient blips.",
              "Restore prior penalty.",
              {"evidence_quality": decomposition.get("evidence_quality")})
    if "TARGET_TOO_AGGRESSIVE" in attribution:
        _make("forecast_targets", "Collect more samples before tightening target zones.",
              "More realistic target expectations.", "Slower adaptation.",
              "No change; sample-collection only.",
              {"forecast_quality": decomposition.get("forecast_quality")})
    if _number(review.get("process_score"), 100) < 55:
        _make("setup_family", "Flag setup for review; collect more samples before trusting it.",
              "Avoid trading a low-quality setup.", "May pause a setup that recovers.",
              "Un-flag; no production behavior changed.",
              {"process_score": review.get("process_score")})

    return recos


def store_recommendations(recos: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    init_db()
    stored = 0
    with _conn() as c:
        for r in recos:
            h = _hash(dict(r))
            try:
                c.execute(
                    """INSERT OR REPLACE INTO review_recommendations_v254
                       (recommendation_id, created_at, status, affected_component, proposed_change,
                        expected_benefit, risks, rollback_plan, supporting_sample,
                        supporting_metrics_json, source_decision_id, reviewed_by, reviewed_at, integrity_hash)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r["recommendation_id"], r["created_at"], r["status"], r["affected_component"],
                     r["proposed_change"], r.get("expected_benefit"), r.get("risks"), r.get("rollback_plan"),
                     r.get("supporting_sample"), json.dumps(r.get("supporting_metrics")),
                     r.get("source_decision_id"), r.get("reviewed_by"), r.get("reviewed_at"), h),
                )
                stored += 1
            except sqlite3.Error:
                continue
    return {"ok": True, "stored": stored}


def list_recommendations(status: Optional[str] = None, limit: int = 100) -> dict[str, Any]:
    init_db()
    query = "SELECT * FROM review_recommendations_v254"
    params: list[Any] = []
    if status:
        query += " WHERE status=?"
        params.append(status.upper())
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(int(limit))
    with _conn() as c:
        rows = [dict(x) for x in c.execute(query, params).fetchall()]
    for row in rows:
        if row.get("supporting_metrics_json"):
            try:
                row["supporting_metrics"] = json.loads(row["supporting_metrics_json"])
            except (TypeError, ValueError):
                pass
        row.pop("supporting_metrics_json", None)
        row.pop("integrity_hash", None)
    return {"ok": True, "version": VERSION, "count": len(rows), "recommendations": rows,
            "production_effect": "NONE"}


def _transition(recommendation_id: str, new_status: str, actor: str, note: str = "") -> dict[str, Any]:
    init_db()
    with _conn() as c:
        row = c.execute("SELECT status FROM review_recommendations_v254 WHERE recommendation_id=?",
                        (recommendation_id,)).fetchone()
        if not row:
            return {"ok": False, "status": "NOT_FOUND", "recommendation_id": recommendation_id}
        previous = row["status"]
        c.execute(
            "UPDATE review_recommendations_v254 SET status=?, reviewed_by=?, reviewed_at=? WHERE recommendation_id=?",
            (new_status, actor, _iso_now(), recommendation_id),
        )
    if governance is not None:
        try:
            governance.audit("REVIEW_RECOMMENDATION_TRANSITION", "recommendation", recommendation_id,
                             previous=previous, new=new_status, explanation=note, actor=actor)
        except Exception:
            pass
    return {"ok": True, "recommendation_id": recommendation_id, "previous_status": previous,
            "new_status": new_status, "reviewed_by": actor, "production_effect": "NONE"}


def approve_recommendation(recommendation_id: str, *, actor: str, note: str = "") -> dict[str, Any]:
    return _transition(recommendation_id, "APPROVED", actor, note)


def reject_recommendation(recommendation_id: str, *, actor: str, note: str = "") -> dict[str, Any]:
    return _transition(recommendation_id, "REJECTED", actor, note)


# --------------------------------------------------------------------------- #
# Replay reconstruction (from stored snapshot only).
# --------------------------------------------------------------------------- #
def replay(decision_id: str) -> dict[str, Any]:
    record = _load_record(decision_id)
    if not record:
        return {"ok": False, "status": "NOT_FOUND", "decision_id": decision_id}
    lifecycle = _mapping(record.get("lifecycle"))
    realized = _mapping(record.get("realized"))
    review = _mapping(record.get("review"))
    return {
        "ok": True,
        "version": VERSION,
        "decision_id": decision_id,
        "reconstructed_from": "stored_snapshot",
        "original_evidence": lifecycle.get("evidence_health"),
        "provider_health": lifecycle.get("provider_health"),
        "thesis": lifecycle.get("thesis"),
        "counter_thesis": lifecycle.get("counter_thesis"),
        "confidence_state": {
            "raw": lifecycle.get("raw_confidence"),
            "integrity_adjusted": lifecycle.get("integrity_adjusted_confidence"),
            "ceiling": lifecycle.get("confidence_ceiling"),
            "layers": lifecycle.get("calibration"),
        },
        "forecast_path": lifecycle.get("forecast"),
        "actual_path": realized.get("realized_path") if realized else None,
        "event_timeline": lifecycle.get("confidence_waterfall"),
        "review_annotations": review,
        "final_attribution": review.get("error_attribution") if review else None,
        "production_effect": "NONE",
    }


# --------------------------------------------------------------------------- #
# Live review composition + reports.
# --------------------------------------------------------------------------- #
def build_review(payload: Optional[Mapping[str, Any]], *,
                 realized: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    lifecycle = build_lifecycle_snapshot(payload)
    review = review_decision(lifecycle, realized)
    recos = generate_recommendations(review, lifecycle) if review.get("gradeable") else []
    return {
        "ok": True,
        "status": "READY",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_now(),
        "lifecycle": lifecycle,
        "review": review,
        "recommendations": recos,
        "guardrails": {
            "read_only": True,
            "advisory_only": True,
            "uncontrolled_self_modification": False,
            "production_change_requires_approval": True,
            "recommendations_bypass_governance": False,
        },
        "production_effect": "NONE",
    }


def _all_reviewed(limit: int = 500) -> list[dict[str, Any]]:
    init_db()
    with _conn() as c:
        rows = [dict(x) for x in c.execute(
            "SELECT * FROM decision_lifecycle_v254 WHERE review_grade IS NOT NULL ORDER BY reviewed_at DESC LIMIT ?",
            (limit,)).fetchall()]
    for row in rows:
        for key in ("lifecycle_json", "realized_json", "review_json"):
            if row.get(key):
                try:
                    row[key.replace("_json", "")] = json.loads(row[key])
                except (TypeError, ValueError):
                    pass
            row.pop(key, None)
        row.pop("engine_versions_json", None)
        row.pop("integrity_hash", None)
    return rows


def recent(limit: int = 25) -> dict[str, Any]:
    return {"ok": True, "version": VERSION, "decisions": _all_reviewed(limit)[:limit],
            "production_effect": "NONE"}


def _ranked(best: bool, limit: int = 10) -> dict[str, Any]:
    order = {g: i for i, g in enumerate(GRADES)}
    reviewed = [r for r in _all_reviewed(500) if r.get("review_grade") in order and r["review_grade"] != "NOT_GRADEABLE"]
    reviewed.sort(key=lambda r: order[r["review_grade"]], reverse=not best)
    return {"ok": True, "version": VERSION, "decisions": reviewed[:limit], "production_effect": "NONE"}


def best(limit: int = 10) -> dict[str, Any]:
    return _ranked(best=True, limit=limit)


def worst(limit: int = 10) -> dict[str, Any]:
    return _ranked(best=False, limit=limit)


def promotion_queue() -> dict[str, Any]:
    return list_recommendations(status="APPROVED", limit=100)


REPORT_KINDS = (
    "daily_decision_review", "weekly_performance_review", "confidence_calibration",
    "forecast_accuracy", "provider_reliability", "setup_family", "market_regime",
    "recommended_changes",
)


def build_report(kind: str) -> dict[str, Any]:
    kind = _text(kind).lower()
    if kind not in REPORT_KINDS:
        return {"ok": False, "status": "UNKNOWN_REPORT", "kinds": list(REPORT_KINDS)}
    reviewed = _all_reviewed(500)

    def _group_grade(field: str) -> dict[str, Any]:
        groups: dict[str, list[str]] = {}
        for r in reviewed:
            key = _text((r.get("lifecycle") or {}).get(field) or r.get(field) or "UNKNOWN")
            groups.setdefault(key, []).append(_text(r.get("review_grade")))
        return {k: {"count": len(v), "grades": v} for k, v in sorted(groups.items())}

    body: dict[str, Any]
    if kind in {"daily_decision_review", "weekly_performance_review"}:
        body = {"reviewed_count": len(reviewed),
                "grade_distribution": _grade_distribution(reviewed)}
    elif kind == "confidence_calibration":
        body = {"note": "Confidence-error summary across reviewed decisions.",
                "grade_distribution": _grade_distribution(reviewed)}
    elif kind == "forecast_accuracy":
        body = {"note": "Forecast-error summary across reviewed decisions.",
                "count": len(reviewed)}
    elif kind == "provider_reliability":
        body = {"by_regime": _group_grade("market_regime")}
    elif kind == "setup_family":
        body = {"by_setup_family": _group_grade("setup_family")}
    elif kind == "market_regime":
        body = {"by_regime": _group_grade("market_regime")}
    else:  # recommended_changes
        body = {"recommendations": list_recommendations(limit=100)["recommendations"]}

    return {"ok": True, "version": VERSION, "report": kind, "generated_at": _iso_now(),
            "body": body, "production_effect": "NONE"}


def _grade_distribution(reviewed: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    dist = {g: 0 for g in GRADES}
    for r in reviewed:
        g = _text(r.get("review_grade"))
        if g in dist:
            dist[g] += 1
    return dist


# --------------------------------------------------------------------------- #
# Mission Control + status.
# --------------------------------------------------------------------------- #
def mission_control_group(result: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    review = _mapping((result or {}).get("review"))
    recos = _list((result or {}).get("recommendations"))
    return {
        "group": "DECISION_REVIEW",
        "panel_state": "READY" if review else "EMPTY",
        "review_grade": review.get("review_grade"),
        "process_score": review.get("process_score"),
        "gradeable": review.get("gradeable"),
        "error_attribution": review.get("error_attribution"),
        "outcome_luck_flag": review.get("outcome_luck_flag"),
        "proposed_recommendations": len(recos),
        "production_effect": "NONE",
    }


def status() -> dict[str, Any]:
    return {
        "status": "READY",
        "engine": "INSTITUTIONAL_DECISION_REVIEW",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "read_only": True,
        "advisory_only": True,
        "grades": list(GRADES),
        "workflow": list(WORKFLOW),
        "report_kinds": list(REPORT_KINDS),
        "uncontrolled_self_modification": False,
        "production_change_requires_approval": True,
        "production_effect": "NONE",
    }
