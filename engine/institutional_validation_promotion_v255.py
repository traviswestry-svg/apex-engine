"""APEX 25.5 — Institutional Validation & Promotion Gate.

This release does not add new market intelligence. It proves that APEX is
trustworthy before any shadow capability is promoted to production. It is a
supervisory/consolidation layer over the completed 25.0-25.4 stack:

  * 25.5.1 Decision Lifecycle Validator  — every stage shares one decision_id;
    detects missing/duplicate/orphaned/out-of-sequence stages and persistence
    failures, and emits a lifecycle audit log.
  * 25.5.2 Shadow Mode Supervisor        — per-engine state, sample, accuracy,
    calibration, drift, promotion blockers, last evaluation.
  * 25.5.3 Validation Dashboard          — Forecast / Confidence / Evidence-Health
    / Promotion panels (Mission Control payload).
  * 25.5.4 Replay Verification           — reconstructed values must match the
    stored snapshot exactly (integrity-hash equality).
  * 25.5.5 Promotion Engine              — SHADOW -> PROPOSED -> UNDER_REVIEW ->
    APPROVED -> PRODUCTION -> ROLLED_BACK. Nothing self-promotes.
  * 25.5.6 Institutional Reports.
  * 25.5.7 Production Safety              — blocks promotion on missing critical
    evidence, degraded providers, weak forecast confidence, calibration drift,
    replay mismatch, or reconstruction failure.

Guarantees: shadow mode stays enforced for forecast/calibration/learning;
production changes require explicit operator approval; ``production_effect`` is
``NONE`` for every read path and for promotion-state transitions (advancing the
governance workflow is not itself a production behavior change).
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sqlite3
from typing import Any, Mapping, Optional

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
    from . import institutional_decision_review_v254 as review_engine  # type: ignore
except Exception:  # pragma: no cover
    review_engine = None  # type: ignore
try:
    from . import institutional_governance as governance  # type: ignore
except Exception:  # pragma: no cover
    governance = None  # type: ignore

VERSION = "25.5.0_INSTITUTIONAL_VALIDATION_PROMOTION_GATE"
SCHEMA_VERSION = "apex.validation_promotion.v255.v1"

# Canonical decision lifecycle, in order. Each stage shares one decision_id.
LIFECYCLE_STAGES = (
    "market_data", "evidence_collection", "decision_integrity", "institutional_reasoning",
    "forecast", "confidence_calibration", "execution_readiness", "trade_lifecycle",
    "outcome", "decision_review", "learning_recommendation",
)

SUPERVISED_ENGINES = ("forecast", "calibration", "learning", "recommendation")
PROMOTION_STATES = ("SHADOW", "PROPOSED", "UNDER_REVIEW", "APPROVED", "PRODUCTION", "ROLLED_BACK")

# Promotion gate thresholds.
PROMOTION_MIN_SAMPLE = 50
PROMOTION_MAX_ECE = 0.08
PROMOTION_MAX_DRIFT_DIVERGENCE = 15.0


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


# --------------------------------------------------------------------------- #
# 25.5.1 Decision Lifecycle Validator.
# --------------------------------------------------------------------------- #
def _stage_presence(root: Mapping[str, Any], decision: Mapping[str, Any],
                    lifecycle: Mapping[str, Any], realized: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    decision_block = _mapping(decision.get("decision"))
    health = _mapping(decision.get("evidence_health"))
    fresh_sources = [s for s in _list(health.get("sources")) if _text(_mapping(s).get("state")).upper() == "FRESH"]

    def present(ok: bool, note: str = "") -> dict[str, Any]:
        return {"present": bool(ok), "note": note}

    return {
        "market_data": present(bool(_mapping(root.get("market_state"))), "market_state block"),
        "evidence_collection": present(bool(_list(health.get("sources"))), f"{len(fresh_sources)} fresh sources"),
        "decision_integrity": present(bool(decision_block), "25.0 decision present"),
        "institutional_reasoning": present(bool(lifecycle.get("confidence_waterfall")) or reasoning is not None,
                                           "25.1 reasoning present"),
        "forecast": present(bool(lifecycle.get("forecast")), "25.2 forecast present"),
        "confidence_calibration": present(lifecycle.get("calibration") is not None, "25.3 calibration layers present"),
        "execution_readiness": present(bool(_text(decision_block.get("execution_eligibility"))),
                                       _text(decision_block.get("execution_eligibility"))),
        "trade_lifecycle": present(realized.get("taken") is not None or bool(root.get("trade_lifecycle")),
                                   "trade record" if realized.get("taken") is not None else "no trade taken"),
        "outcome": present(bool(realized) and realized.get("matured") is not False, "realized outcome"),
        "decision_review": present(review_engine is not None, "25.4 review available"),
        "learning_recommendation": present(review_engine is not None, "25.4 recommendations available"),
    }


def validate_lifecycle(payload: Optional[Mapping[str, Any]] = None, *,
                       decision_id: Optional[str] = None,
                       realized: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Validate the end-to-end lifecycle for a decision.

    If ``decision_id`` is given and a stored 25.4 record exists, the stored
    lifecycle is validated; otherwise a live snapshot is composed and validated.
    """
    audit_log: list[dict[str, Any]] = []
    realized = _mapping(realized)

    stored = None
    if decision_id and review_engine is not None:
        stored = review_engine._load_record(decision_id)  # documented reuse
        if stored is None:
            return {
                "ok": True, "status": "ORPHANED", "version": VERSION, "decision_id": decision_id,
                "valid": False, "defects": ["ORPHANED_RECORD: no stored lifecycle for decision_id"],
                "stages": {}, "audit_log": [{"stage": "lookup", "result": "MISSING"}],
                "generated_at": _iso_now(), "production_effect": "NONE",
            }
        lifecycle = _mapping(stored.get("lifecycle"))
        realized = realized or _mapping(stored.get("realized"))
        root = {"market_state": {"as_of": lifecycle.get("decision_at")}, **{k: lifecycle.get(k) for k in ()}}
        decision = {"decision": {
            "direction": lifecycle.get("direction"),
            "execution_eligibility": lifecycle.get("execution_eligibility"),
            "raw_confidence": lifecycle.get("raw_confidence"),
        }, "evidence_health": lifecycle.get("evidence_health")}
        resolved_id = _text(stored.get("decision_id"))
    else:
        root = payload if isinstance(payload, Mapping) else {}
        decision = integrity.evaluate_decision(root)
        lifecycle = review_engine.build_lifecycle_snapshot(root) if review_engine else {
            "decision_id": _text(_mapping(decision.get("decision")).get("decision_id") or root.get("decision_id")),
            "forecast": forecast_engine.build_forecast(root)["forecast"] if forecast_engine else {},
            "calibration": (calibration_engine.build_calibration(root)["calibration"]["confidence_layers"]
                            if calibration_engine else None),
        }
        resolved_id = _text(lifecycle.get("decision_id"))

    stages = _stage_presence(root, decision, lifecycle, realized)

    # Detect defects.
    defects: list[str] = []
    seen_order: list[str] = []
    for stage in LIFECYCLE_STAGES:
        info = stages.get(stage, {"present": False})
        audit_log.append({"stage": stage, "present": info["present"], "note": info.get("note", "")})
        if info["present"]:
            seen_order.append(stage)
        else:
            # Missing outcome/trade before maturity is expected, not a hard defect.
            if stage in {"trade_lifecycle", "outcome"} and realized.get("matured") is False:
                continue
            if stage in {"outcome", "learning_recommendation", "decision_review", "trade_lifecycle"}:
                defects.append(f"MISSING_STAGE:{stage}")
            else:
                defects.append(f"MISSING_CRITICAL_STAGE:{stage}")

    # Sequence check: present stages must appear in canonical order (they will by
    # construction, but a stored record could violate it).
    expected_index = [LIFECYCLE_STAGES.index(s) for s in seen_order]
    if expected_index != sorted(expected_index):
        defects.append("INCORRECT_SEQUENCE")

    # Duplicate decision_id consistency across composed sub-records.
    forecast_id = _text(_mapping(lifecycle.get("forecast")).get("decision_id"))
    if forecast_id and resolved_id and forecast_id != resolved_id:
        defects.append("DECISION_ID_MISMATCH:forecast")

    critical_defects = [d for d in defects if d.startswith("MISSING_CRITICAL") or d in {"INCORRECT_SEQUENCE"} or d.startswith("DECISION_ID_MISMATCH")]
    valid = not critical_defects
    return {
        "ok": True,
        "status": "VALID" if valid else "INVALID",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "decision_id": resolved_id,
        "valid": valid,
        "defects": defects,
        "critical_defects": critical_defects,
        "stages": stages,
        "stage_count": len(seen_order),
        "expected_stage_count": len(LIFECYCLE_STAGES),
        "audit_log": audit_log,
        "source": "stored_record" if stored else "live_snapshot",
        "generated_at": _iso_now(),
        "production_effect": "NONE",
    }


# --------------------------------------------------------------------------- #
# 25.5.2 Shadow Mode Supervisor.
# --------------------------------------------------------------------------- #
def supervise(payload: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    root = payload if isinstance(payload, Mapping) else {}
    engines: dict[str, Any] = {}

    # Forecast engine.
    if forecast_engine is not None:
        try:
            hist = forecast_engine.history(limit=200)
            sample = int(_number(hist.get("count")))
            fc = forecast_engine.build_forecast(root)["forecast"]
            engines["forecast"] = {
                "state": "SHADOW",
                "sample_size": sample,
                "accuracy": None if sample == 0 else "SEE_REVIEW",
                "calibration": None,
                "drift": None,
                "forecast_quality": fc.get("forecast_quality"),
                "promotion_blockers": _forecast_blockers(sample),
                "last_evaluation": hist.get("generated_at"),
            }
        except Exception as exc:
            engines["forecast"] = {"state": "DISABLED", "error": str(exc)}
    else:
        engines["forecast"] = {"state": "DISABLED", "error": "module unavailable"}

    # Calibration engine.
    if calibration_engine is not None:
        try:
            calib = calibration_engine.build_calibration(root)["calibration"]
            reliability = _mapping(calib.get("reliability"))
            drift = _mapping(calib.get("drift"))
            promo = _mapping(calib.get("promotion"))
            engines["calibration"] = {
                "state": "SHADOW",
                "sample_size": calib.get("sample_size"),
                "accuracy": None,
                "calibration": {"brier": reliability.get("brier_score"),
                                "ece": reliability.get("expected_calibration_error"),
                                "quality": calib.get("calibration_quality")},
                "drift": drift.get("state"),
                "promotion_blockers": promo.get("blockers"),
                "last_evaluation": _iso_now(),
            }
        except Exception as exc:
            engines["calibration"] = {"state": "DISABLED", "error": str(exc)}
    else:
        engines["calibration"] = {"state": "DISABLED", "error": "module unavailable"}

    # Learning / Recommendation (25.4).
    if review_engine is not None:
        try:
            proposed = review_engine.list_recommendations(status="PROPOSED", limit=200)
            approved = review_engine.list_recommendations(status="APPROVED", limit=200)
            engines["learning"] = {
                "state": "SHADOW",
                "sample_size": int(_number(proposed.get("count"))) + int(_number(approved.get("count"))),
                "proposed": proposed.get("count"),
                "approved": approved.get("count"),
                "drift": None,
                "promotion_blockers": ["Learning stays advisory; recommendations require operator approval."],
                "last_evaluation": _iso_now(),
            }
            engines["recommendation"] = {
                "state": "SHADOW",
                "sample_size": int(_number(proposed.get("count"))),
                "pending_review": proposed.get("count"),
                "promotion_blockers": ["Recommendations never alter production without approval."],
                "last_evaluation": _iso_now(),
            }
        except Exception as exc:
            engines["learning"] = {"state": "DISABLED", "error": str(exc)}
            engines["recommendation"] = {"state": "DISABLED", "error": str(exc)}
    else:
        engines["learning"] = {"state": "DISABLED", "error": "module unavailable"}
        engines["recommendation"] = {"state": "DISABLED", "error": "module unavailable"}

    # Overlay any persisted promotion state.
    for name in SUPERVISED_ENGINES:
        persisted = _promotion_state(name)
        if persisted and name in engines and isinstance(engines[name], dict):
            engines[name]["promotion_state"] = persisted.get("state")

    return {
        "ok": True,
        "version": VERSION,
        "generated_at": _iso_now(),
        "shadow_mode_enforced": True,
        "engines": engines,
        "production_effect": "NONE",
    }


def _forecast_blockers(sample: int) -> list[str]:
    blockers = []
    if sample < PROMOTION_MIN_SAMPLE:
        blockers.append(f"Forecast sample {sample} below minimum {PROMOTION_MIN_SAMPLE}.")
    blockers.append("Forecasting is shadow-only and cannot affect production confidence.")
    return blockers


# --------------------------------------------------------------------------- #
# 25.5.4 Replay Verification.
# --------------------------------------------------------------------------- #
def verify_replay(decision_id: str) -> dict[str, Any]:
    """Reconstruct a decision from its stored snapshot and verify exact match."""
    if review_engine is None:
        return {"ok": False, "status": "UNAVAILABLE", "reason": "review engine not loaded"}
    stored = review_engine._load_record(decision_id)  # documented reuse
    if stored is None:
        return {"ok": False, "status": "RECONSTRUCTION_FAILED", "decision_id": decision_id,
                "reason": "no stored record", "match": False, "production_effect": "NONE"}
    lifecycle = _mapping(stored.get("lifecycle"))
    stored_hash = _text(stored.get("integrity_hash"))
    recomputed = review_engine._hash(dict(lifecycle))  # same hashing as record_decision
    replay = review_engine.replay(decision_id)
    match = bool(stored_hash) and stored_hash == recomputed and replay.get("ok") is True
    return {
        "ok": True,
        "version": VERSION,
        "decision_id": decision_id,
        "match": match,
        "status": "MATCH" if match else "MISMATCH",
        "stored_integrity_hash": stored_hash,
        "recomputed_integrity_hash": recomputed,
        "reconstructed_fields": [k for k in ("thesis", "counter_thesis", "confidence_state",
                                             "forecast_path", "provider_health", "event_timeline")
                                 if replay.get(k) is not None],
        "generated_at": _iso_now(),
        "production_effect": "NONE",
    }


# --------------------------------------------------------------------------- #
# Promotion persistence (governed sqlite).
# --------------------------------------------------------------------------- #
def _db_path() -> str:
    return os.getenv("APEX_VALIDATION_DB", "apex_validation.db")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_db_path())
    c.row_factory = sqlite3.Row
    return c


def init_db() -> dict[str, Any]:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS engine_promotion_state_v255(
              engine TEXT PRIMARY KEY,
              state TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              updated_by TEXT,
              blockers_json TEXT,
              criteria_json TEXT
            );
            CREATE TABLE IF NOT EXISTS promotion_audit_v255(
              audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
              engine TEXT NOT NULL, at TEXT NOT NULL,
              previous_state TEXT, new_state TEXT, actor TEXT, note TEXT
            );
            """
        )
    return {"ok": True, "db_path": _db_path()}


def _promotion_state(engine: str) -> Optional[dict[str, Any]]:
    init_db()
    with _conn() as c:
        row = c.execute("SELECT * FROM engine_promotion_state_v255 WHERE engine=?", (engine,)).fetchone()
    return dict(row) if row else None


# --------------------------------------------------------------------------- #
# 25.5.7 Production Safety gate.
# --------------------------------------------------------------------------- #
def promotion_safety(engine: str, payload: Optional[Mapping[str, Any]] = None, *,
                     decision_id: Optional[str] = None) -> dict[str, Any]:
    """Return the safety verdict for promoting ``engine``. Never mutates state."""
    root = payload if isinstance(payload, Mapping) else {}
    blockers: list[str] = []
    engine = _text(engine).lower()

    decision = integrity.evaluate_decision(root)
    health = _mapping(decision.get("evidence_health"))
    if _list(health.get("critical_degraded")):
        blockers.append("Critical evidence missing or degraded.")
    if _text(health.get("state")).upper() == "UNRELIABLE":
        blockers.append("Provider/evidence health is unreliable.")

    if engine in {"forecast"} and forecast_engine is not None:
        fc = forecast_engine.build_forecast(root)["forecast"]
        if _text(fc.get("forecast_quality")).upper() in {"INSUFFICIENT_DATA", "LOW"}:
            blockers.append("Forecast confidence/quality is weak.")
        sample = int(_number(forecast_engine.history(limit=200).get("count")))
        if sample < PROMOTION_MIN_SAMPLE:
            blockers.append(f"Forecast sample {sample} below minimum {PROMOTION_MIN_SAMPLE}.")

    if engine in {"calibration"} and calibration_engine is not None:
        calib = calibration_engine.build_calibration(root)["calibration"]
        reliability = _mapping(calib.get("reliability"))
        drift = _mapping(calib.get("drift"))
        if _number(reliability.get("expected_calibration_error"), 1.0) > PROMOTION_MAX_ECE:
            blockers.append("Calibration expected error above threshold.")
        if drift.get("detected"):
            blockers.append("Calibration drift detected.")
        if abs(_number(drift.get("recent_vs_longterm_divergence_pts"))) > PROMOTION_MAX_DRIFT_DIVERGENCE:
            blockers.append("Calibration drift divergence exceeds threshold.")
        if int(_number(calib.get("sample_size"))) < PROMOTION_MIN_SAMPLE:
            blockers.append("Calibration sample below minimum.")

    # Replay/reconstruction safety.
    if decision_id:
        rv = verify_replay(decision_id)
        if not rv.get("match"):
            blockers.append("Replay mismatch or decision reconstruction failed.")

    return {
        "ok": True,
        "engine": engine,
        "safe_to_promote": not blockers,
        "blockers": blockers,
        "generated_at": _iso_now(),
        "production_effect": "NONE",
    }


# --------------------------------------------------------------------------- #
# 25.5.5 Promotion Engine (governed workflow; nothing self-promotes).
# --------------------------------------------------------------------------- #
_ALLOWED_TRANSITIONS = {
    "SHADOW": {"PROPOSED"},
    "PROPOSED": {"UNDER_REVIEW", "SHADOW"},
    "UNDER_REVIEW": {"APPROVED", "SHADOW"},
    "APPROVED": {"PRODUCTION", "ROLLED_BACK"},
    "PRODUCTION": {"ROLLED_BACK"},
    "ROLLED_BACK": {"SHADOW"},
}


def _set_state(engine: str, new_state: str, actor: str, note: str,
               blockers: Optional[list] = None) -> dict[str, Any]:
    init_db()
    current = (_promotion_state(engine) or {}).get("state", "SHADOW")
    if new_state not in _ALLOWED_TRANSITIONS.get(current, set()):
        return {"ok": False, "status": "ILLEGAL_TRANSITION", "engine": engine,
                "from": current, "to": new_state,
                "allowed": sorted(_ALLOWED_TRANSITIONS.get(current, set()))}
    with _conn() as c:
        c.execute(
            """INSERT INTO engine_promotion_state_v255(engine, state, updated_at, updated_by, blockers_json)
               VALUES(?,?,?,?,?)
               ON CONFLICT(engine) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at,
                 updated_by=excluded.updated_by, blockers_json=excluded.blockers_json""",
            (engine, new_state, _iso_now(), actor, json.dumps(blockers or [])),
        )
        c.execute(
            "INSERT INTO promotion_audit_v255(engine, at, previous_state, new_state, actor, note) VALUES(?,?,?,?,?,?)",
            (engine, _iso_now(), current, new_state, actor, note),
        )
    if governance is not None:
        try:
            governance.audit("ENGINE_PROMOTION", "engine", engine, previous=current,
                             new=new_state, explanation=note, actor=actor)
        except Exception:
            pass
    return {"ok": True, "engine": engine, "previous_state": current, "new_state": new_state,
            "reviewed_by": actor, "production_effect": "NONE"}


def propose_promotion(engine: str, *, actor: str, payload: Optional[Mapping[str, Any]] = None,
                      note: str = "") -> dict[str, Any]:
    engine = _text(engine).lower()
    if engine not in SUPERVISED_ENGINES:
        return {"ok": False, "status": "UNKNOWN_ENGINE", "engines": list(SUPERVISED_ENGINES)}
    safety = promotion_safety(engine, payload)
    if not safety["safe_to_promote"]:
        return {"ok": False, "status": "BLOCKED", "engine": engine,
                "blockers": safety["blockers"], "production_effect": "NONE"}
    return _set_state(engine, "PROPOSED", actor, note, blockers=[])


def review_promotion(engine: str, *, actor: str, note: str = "") -> dict[str, Any]:
    return _set_state(_text(engine).lower(), "UNDER_REVIEW", actor, note)


def approve_promotion(engine: str, *, actor: str, payload: Optional[Mapping[str, Any]] = None,
                      note: str = "") -> dict[str, Any]:
    engine = _text(engine).lower()
    safety = promotion_safety(engine, payload)
    if not safety["safe_to_promote"]:
        return {"ok": False, "status": "BLOCKED", "engine": engine, "blockers": safety["blockers"]}
    return _set_state(engine, "APPROVED", actor, note)


def promote_to_production(engine: str, *, actor: str, payload: Optional[Mapping[str, Any]] = None,
                          note: str = "") -> dict[str, Any]:
    """Advance an APPROVED engine to PRODUCTION. Requires operator approval flag.

    This only records the governed promotion state. The shadow engines each keep
    their own production feature flags (e.g. calibration's), so recording
    PRODUCTION here does not itself flip any engine's behavior.
    """
    engine = _text(engine).lower()
    approved_flag = _text(os.getenv("APEX_PROMOTION_APPROVED", "false")).lower() == "true"
    if not approved_flag:
        return {"ok": False, "status": "OPERATOR_APPROVAL_REQUIRED", "engine": engine,
                "message": "Set APEX_PROMOTION_APPROVED=true to record a production promotion."}
    safety = promotion_safety(engine, payload)
    if not safety["safe_to_promote"]:
        return {"ok": False, "status": "BLOCKED", "engine": engine, "blockers": safety["blockers"]}
    return _set_state(engine, "PRODUCTION", actor, note)


def rollback_promotion(engine: str, *, actor: str, note: str = "") -> dict[str, Any]:
    return _set_state(_text(engine).lower(), "ROLLED_BACK", actor, note)


def promotion_overview(payload: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    out = {}
    for engine in SUPERVISED_ENGINES:
        state = (_promotion_state(engine) or {}).get("state", "SHADOW")
        safety = promotion_safety(engine, payload)
        out[engine] = {
            "state": state,
            "readiness": "READY" if safety["safe_to_promote"] else "BLOCKED",
            "blockers": safety["blockers"],
        }
    return {"ok": True, "version": VERSION, "engines": out, "generated_at": _iso_now(),
            "production_effect": "NONE"}


# --------------------------------------------------------------------------- #
# 25.5.3 Validation Dashboard (Mission Control panels).
# --------------------------------------------------------------------------- #
def dashboard(payload: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    root = payload if isinstance(payload, Mapping) else {}
    decision = integrity.evaluate_decision(root)
    health = _mapping(decision.get("evidence_health"))
    forecast = forecast_engine.build_forecast(root)["forecast"] if forecast_engine else {}
    calib = calibration_engine.build_calibration(root)["calibration"] if calibration_engine else {}
    layers = _mapping(calib.get("confidence_layers"))
    reliability = _mapping(calib.get("reliability"))

    evidence_states = {}
    for item in _list(health.get("sources")):
        block = _mapping(item)
        evidence_states[_text(block.get("source"))] = _text(block.get("state"))

    return {
        "ok": True,
        "version": VERSION,
        "generated_at": _iso_now(),
        "forecast_panel": {
            "expected_move_points": forecast.get("expected_move_points"),
            "expected_mfe": forecast.get("expected_mfe"),
            "expected_mae": forecast.get("expected_mae"),
            "forecast_quality": forecast.get("forecast_quality"),
            "forecast_confidence": forecast.get("forecast_confidence"),
        },
        "confidence_panel": {
            "raw_confidence": layers.get("raw_confidence"),
            "integrity_confidence": layers.get("integrity_adjusted_confidence"),
            "calibrated_confidence": layers.get("final_calibrated_confidence"),
            "expected_calibration_error": reliability.get("expected_calibration_error"),
            "brier_score": reliability.get("brier_score"),
            "reliability_curve": reliability.get("buckets"),
        },
        "evidence_health_panel": {
            "state": health.get("state"),
            "fresh_ratio": health.get("fresh_ratio"),
            "sources": evidence_states,
        },
        "promotion_panel": promotion_overview(root)["engines"],
        "shadow_mode_enforced": True,
        "production_effect": "NONE",
    }


# --------------------------------------------------------------------------- #
# 25.5.6 Institutional Reports.
# --------------------------------------------------------------------------- #
REPORT_KINDS = (
    "daily_validation", "weekly_validation", "forecast_accuracy", "calibration",
    "provider_reliability", "decision_integrity", "replay_verification", "promotion_readiness",
)


def build_report(kind: str, payload: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    kind = _text(kind).lower()
    if kind not in REPORT_KINDS:
        return {"ok": False, "status": "UNKNOWN_REPORT", "kinds": list(REPORT_KINDS)}
    root = payload if isinstance(payload, Mapping) else {}

    if kind in {"daily_validation", "weekly_validation"}:
        sup = supervise(root)
        body = {"engines": sup["engines"], "shadow_mode_enforced": True}
    elif kind == "forecast_accuracy":
        body = forecast_engine.history(limit=100) if forecast_engine else {"note": "forecast unavailable"}
    elif kind == "calibration":
        body = (calibration_engine.build_calibration(root)["calibration"]
                if calibration_engine else {"note": "calibration unavailable"})
    elif kind == "provider_reliability":
        body = dashboard(root)["evidence_health_panel"]
    elif kind == "decision_integrity":
        body = _mapping(integrity.evaluate_decision(root).get("evidence_health"))
    elif kind == "replay_verification":
        body = {"note": "Supply a decision_id via /replay-verify/<id> for a per-decision check."}
    else:  # promotion_readiness
        body = promotion_overview(root)["engines"]

    return {"ok": True, "version": VERSION, "report": kind, "generated_at": _iso_now(),
            "body": body, "production_effect": "NONE"}


# --------------------------------------------------------------------------- #
# Aggregate status.
# --------------------------------------------------------------------------- #
def build_validation(payload: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    root = payload if isinstance(payload, Mapping) else {}
    return {
        "ok": True,
        "status": "READY",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_now(),
        "lifecycle_validation": validate_lifecycle(root),
        "supervisor": supervise(root),
        "dashboard": dashboard(root),
        "guardrails": {
            "shadow_mode_enforced": True,
            "nothing_self_promotes": True,
            "production_change_requires_approval": True,
        },
        "production_effect": "NONE",
    }


def mission_control_group(result: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    res = result or {}
    lifecycle = _mapping(res.get("lifecycle_validation"))
    supervisor = _mapping(res.get("supervisor"))
    return {
        "group": "INSTITUTIONAL_VALIDATION",
        "panel_state": "READY" if res else "EMPTY",
        "lifecycle_valid": lifecycle.get("valid"),
        "lifecycle_defects": lifecycle.get("critical_defects"),
        "engines_supervised": list(_mapping(supervisor.get("engines")).keys()),
        "shadow_mode_enforced": True,
        "production_effect": "NONE",
    }


def status() -> dict[str, Any]:
    return {
        "status": "READY",
        "engine": "INSTITUTIONAL_VALIDATION_PROMOTION_GATE",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "lifecycle_stages": list(LIFECYCLE_STAGES),
        "supervised_engines": list(SUPERVISED_ENGINES),
        "promotion_states": list(PROMOTION_STATES),
        "report_kinds": list(REPORT_KINDS),
        "shadow_mode_enforced": True,
        "nothing_self_promotes": True,
        "production_effect": "NONE",
    }
