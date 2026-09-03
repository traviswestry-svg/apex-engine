"""APEX 69.9.9 — Live Actionability Capture Probe & Lifecycle Attribution Closure.

Runtime-only bridge connecting the canonical Institutional OS decision to the
existing durable evidence ledger.  This module is observational: it never
changes trade decisions, confidence, thresholds, or execution authority.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .evidence_pipeline import DEFAULT_DB, readiness, record_price, record_snapshot
from .outcome_grader import run_grader
from .canonical_persistence import connect as canonical_connect

VERSION = "69.9.9"
SCHEMA_VERSION = "apex.historical_evidence_lifecycle.v1.6"

_LOCK = threading.RLock()
_RUNTIME: Dict[str, Any] = {
    "decision_attempts": 0,
    "decisions_inserted": 0,
    "decision_duplicates": 0,
    "decision_errors": 0,
    "price_attempts": 0,
    "prices_written": 0,
    "price_errors": 0,
    "grader_runs": 0,
    "grader_errors": 0,
    "last_decision_at": None,
    "last_price_at": None,
    "last_grade_at": None,
    "last_grade_result": None,
    "market_memory_captures": 0,
    "market_memory_duplicates": 0,
    "market_memory_errors": 0,
    "actionability_capture_attempts": 0,
    "actionability_capture_ready": 0,
    "actionability_capture_missing": 0,
    "last_actionability_capture_at": None,
    "last_actionability_capture_version": None,
    "last_entry_window_source": None,
    "last_entry_cutoff_et": None,
    "last_cutoff_passed": None,
    "last_actionability_capture_provenance": {},
}
_MEMORY_KEYS: set[str] = set()


def _m(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _f(value: Any) -> Optional[float]:
    try:
        x = float(value)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _release_version() -> Optional[str]:
    """Read canonical release identity for observational cohort attribution."""
    try:
        manifest = Path(__file__).resolve().parents[1] / "config" / "apex_release_manifest.json"
        payload = json.loads(manifest.read_text())
        value = str(payload.get("apex_version") or "").strip()
        return value or None
    except Exception:
        return None


def _path(source: Mapping[str, Any], *paths: str) -> Any:
    for path in paths:
        cur: Any = source
        ok = True
        for key in path.split("."):
            if not isinstance(cur, Mapping) or key not in cur:
                ok = False
                break
            cur = cur[key]
        if ok and cur not in (None, ""):
            return cur
    return None


def _decision_time(timestamp: Any) -> dt.datetime:
    """Parse the finalized canonical decision timestamp for deterministic capture."""
    try:
        value = dt.datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value
    except Exception:
        return dt.datetime.now(dt.timezone.utc)


def _capture_status(*, present: bool, value: Any, source: str,
                    derived: bool = False, error: Optional[str] = None) -> Dict[str, Any]:
    if error:
        status = "SOURCE_ERROR"
    elif not present:
        status = "SOURCE_PATH_NOT_FOUND"
    elif value is None or value == "":
        status = "SOURCE_PRESENT_NULL"
    elif derived:
        status = "DERIVED_FROM_DECISION_TIME_POLICY"
    else:
        status = "SOURCE_PRESENT"
    out = {"status": status, "source": source}
    if error:
        out["error"] = error
    return out


def _recommendation_capture(root: Mapping[str, Any]) -> tuple[Any, Any, str, bool]:
    """Normalize the scanner recommendation without inventing a recommendation.

    Production scanner composition may expose ``recommendation`` as a string, while
    Trade Director surfaces often expose a mapping.  69.9.6 treated strings as an
    empty mapping, which is why live captures showed UNKNOWN despite a real source.
    """
    raw = root.get("recommendation")
    if isinstance(raw, Mapping):
        m = dict(raw)
        return m.get("action"), m.get("state"), "result.recommendation(mapping)", True
    if isinstance(raw, str) and raw.strip():
        return raw.strip(), None, "result.recommendation(string)", True
    premium = root.get("premium_strategy")
    if isinstance(premium, Mapping):
        m = dict(premium)
        return m.get("action"), m.get("state"), "result.premium_strategy(mapping)", True
    return None, None, "result.recommendation|result.premium_strategy", False


def _decision_id(ticker: str, timestamp: str, action: str, direction: str) -> str:
    raw = f"69.0|{ticker}|{timestamp}|{action}|{direction}"
    return "apex69_" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def _extract_price(result: Mapping[str, Any], ido: Mapping[str, Any]) -> Optional[float]:
    for value in (
        _path(ido, "market_state.price", "market_state.spot", "entry_price"),
        _path(result, "market_state.price", "market_state.spot", "spot", "price", "underlying_price", "flow.stock_price"),
    ):
        price = _f(value)
        if price is not None and price > 0:
            return price
    return None


def _extract_confidence(result: Mapping[str, Any], ido: Mapping[str, Any]) -> Optional[float]:
    value = _path(
        ido,
        "conviction.score",
        "conviction.calibrated_conviction",
        "calibrated_conviction",
        "raw_conviction",
    )
    if value is None:
        value = _path(result, "confidence", "institutional_confidence", "ici")
    return _f(value)


def build_snapshot(result: Mapping[str, Any], *, session_state: Optional[str] = None) -> Dict[str, Any]:
    """Build one bounded, decision-time-only snapshot from a composed IOS result."""
    root = dict(result or {})
    ido = _m(root.get("institutional_decision_object"))
    ticker = str(ido.get("ticker") or root.get("ticker") or "SPX").upper()
    timestamp = str(ido.get("timestamp") or ido.get("generated_at") or root.get("generated_at") or _now())
    action = str(ido.get("action") or ido.get("decision_state") or "NO_TRADE").upper()
    direction = str(ido.get("direction") or "NEUTRAL").upper()
    blocked_actions = {"NO_TRADE", "STAND_DOWN", "ABSTAIN", "WATCH", "WATCH_ONLY"}
    explicit_actionable = bool(ido.get("actionable"))
    execution_actionable = explicit_actionable and action not in blocked_actions
    price = _extract_price(root, ido)
    confidence = _extract_confidence(root, ido)

    # APEX 69.4.1 — preserve the directional thesis BEFORE final execution
    # governance separately from the final action. A governed NO_TRADE remains
    # non-executable, but a real-time BULLISH/BEARISH thesis with a contemporaneous
    # price may be graded observationally as an abstention/counterfactual.
    thesis = _m(ido.get("institutional_thesis") or ido.get("thesis"))
    consensus = _m(ido.get("institutional_consensus") or ido.get("consensus"))
    conviction = _m(ido.get("conviction"))
    thesis_direction = str(
        thesis.get("dominant_direction") or consensus.get("dominant_direction") or direction
    ).upper()
    observational_eligible = (
        thesis_direction in {"BULLISH", "BEARISH"}
        and price is not None
        and str(session_state or root.get("session") or "UNKNOWN").upper()
            not in {"CLOSED", "MARKET_CLOSED", "AFTER_HOURS"}
    )
    learning_eligible = execution_actionable or observational_eligible
    if execution_actionable:
        eligibility_reason = "EXECUTION_ELIGIBLE"
    elif observational_eligible:
        eligibility_reason = "OBSERVATIONAL_DIRECTIONAL_THESIS"
    elif action in blocked_actions:
        eligibility_reason = f"ACTION_{action}"
    elif not explicit_actionable:
        eligibility_reason = "IDO_ACTIONABLE_FALSE_OR_MISSING"
    elif direction in {"", "NEUTRAL", "UNKNOWN", "NONE"}:
        eligibility_reason = "DIRECTION_NOT_DIRECTIONAL"
    else:
        eligibility_reason = "NOT_GRADE_ELIGIBLE"

    # APEX 69.9.2 — reconstruct the observational dynamic-state context from the
    # exact finalized composition snapshot. This occurs after the canonical decision
    # is complete and cannot feed back into that decision.
    try:
        from .dynamic_state import build_dynamic_state
        observed_dynamic_state = build_dynamic_state(root)
    except Exception:
        observed_dynamic_state = {}

    # The finalized IDO already carries the policy used by conviction/consensus.
    # Prefer that exact policy over recomputation so historical context reflects
    # the decision-time governance state.
    ido_conviction = _m(ido.get("conviction"))
    ido_consensus = _m(ido.get("institutional_consensus") or ido.get("consensus"))
    observed_dynamic_policy = (
        _m(ido_conviction.get("dynamic_state_policy"))
        or _m(ido_consensus.get("dynamic_state_policy"))
        or _m(root.get("dynamic_state_policy"))
    )

    # APEX 69.9.7 — freeze decision-time actionability from sources that are
    # actually present on the scanner composition path. Trade Director Phase 11 is
    # not guaranteed to exist on this result at canonical evidence capture time, so
    # the exact entry-window policy is additionally read from the same RiskLimits
    # contract enforced by engine.execution.trade_risk_guard. This is observational
    # provenance only and cannot approve or reject an order.
    session_intelligence = _m(root.get("session_intelligence"))
    session_authority = _m(session_intelligence.get("session"))
    market_narrative = _m(ido.get("market_narrative") or ido.get("narrative"))
    recommendation_action, recommendation_state, recommendation_source, recommendation_present = _recommendation_capture(root)

    risk_policy: Dict[str, Any] = {}
    risk_policy_error: Optional[str] = None
    try:
        from .execution.trade_risk_guard import entry_window_policy_snapshot
        risk_policy = entry_window_policy_snapshot(
            now=_decision_time(timestamp),
            session_state=str(session_state or root.get("session") or "UNKNOWN").upper(),
        )
    except Exception as exc:
        risk_policy_error = f"{type(exc).__name__}: {exc}"
        risk_policy = {}

    session_cutoff_present = "cutoff" in session_authority and session_authority.get("cutoff") not in (None, "")
    session_cutoff_passed_present = "cutoff_passed" in session_authority
    risk_cutoff_present = bool(risk_policy.get("entry_cutoff_et")) and bool(risk_policy.get("cutoff_parse_ok"))
    risk_cutoff_passed_present = risk_policy.get("cutoff_passed") is not None

    if session_cutoff_present and session_cutoff_passed_present:
        entry_cutoff_et = session_authority.get("cutoff")
        cutoff_passed = bool(session_authority.get("cutoff_passed"))
        entry_window_source = "SESSION_INTELLIGENCE"
        entry_window_source_present = True
        cutoff_source = "result.session_intelligence.session.cutoff"
        cutoff_passed_source = "result.session_intelligence.session.cutoff_passed"
        cutoff_derived = False
    elif risk_cutoff_present and risk_cutoff_passed_present:
        entry_cutoff_et = risk_policy.get("entry_cutoff_et")
        cutoff_passed = bool(risk_policy.get("cutoff_passed"))
        entry_window_source = "TRADE_RISK_GUARD_POLICY"
        entry_window_source_present = True
        cutoff_source = "engine.execution.trade_risk_guard.RiskLimits.no_new_trades_after_et"
        cutoff_passed_source = "engine.execution.trade_risk_guard.entry_window_policy_snapshot"
        cutoff_derived = True
    else:
        entry_cutoff_et = None
        cutoff_passed = None
        entry_window_source = "UNAVAILABLE"
        entry_window_source_present = False
        cutoff_source = "result.session_intelligence.session.cutoff|trade_risk_guard.RiskLimits.no_new_trades_after_et"
        cutoff_passed_source = "result.session_intelligence.session.cutoff_passed|trade_risk_guard.entry_window_policy_snapshot"
        cutoff_derived = False

    trade_guidance_present = "trade_guidance_enabled" in market_narrative
    thesis_state_present = "state" in thesis
    conviction_score_present = "score" in conviction
    session_mode_present = "mode" in session_authority

    actionability_capture = {
        "schema_version": "apex.counterfactual_actionability_capture.v2",
        "capture_version": VERSION,
        "session_intelligence_present": bool(session_intelligence),
        "session_mode": session_authority.get("mode"),
        "entry_window_source": entry_window_source,
        "entry_window_source_present": entry_window_source_present,
        "entry_cutoff_et": entry_cutoff_et,
        "cutoff_passed": cutoff_passed,
        "entry_window_authorized": (
            bool(risk_policy.get("entry_window_authorized"))
            if entry_window_source == "TRADE_RISK_GUARD_POLICY" else
            (not cutoff_passed if entry_window_source_present else None)
        ),
        "market_session": str(session_state or root.get("session") or "UNKNOWN").upper(),
        "market_session_authorized_by_entry_policy": (
            risk_policy.get("market_session_authorized") if risk_policy else None
        ),
        "trade_guidance_enabled": (
            bool(market_narrative.get("trade_guidance_enabled"))
            if trade_guidance_present else None
        ),
        "thesis_state": thesis.get("state"),
        "direction": thesis_direction if thesis_direction in {"BULLISH", "BEARISH"} else direction,
        "conviction_score": conviction.get("score"),
        "blocking_conditions": list(conviction.get("blocking_conditions") or []),
        "ido_actionable": explicit_actionable,
        "ido_status": ido.get("status"),
        "recommendation_action": recommendation_action,
        "recommendation_state": recommendation_state,
        "recommendation_source": recommendation_source,
        "final_action": action,
        "entry_reference_available": price is not None,
        "targets_and_decision_levels": _m(ido.get("targets_and_decision_levels")),
        "dynamic_policy_state": observed_dynamic_policy.get("state"),
        "dynamic_policy_blocking_conditions": list(observed_dynamic_policy.get("blocking_conditions") or []),
        "capture_provenance": {
            "session_mode": _capture_status(
                present=session_mode_present, value=session_authority.get("mode"),
                source="result.session_intelligence.session.mode",
            ),
            "entry_cutoff_et": _capture_status(
                present=entry_window_source_present, value=entry_cutoff_et,
                source=cutoff_source, derived=cutoff_derived, error=risk_policy_error,
            ),
            "cutoff_passed": _capture_status(
                present=entry_window_source_present, value=cutoff_passed,
                source=cutoff_passed_source, derived=cutoff_derived, error=risk_policy_error,
            ),
            "trade_guidance_enabled": _capture_status(
                present=trade_guidance_present, value=market_narrative.get("trade_guidance_enabled"),
                source="institutional_decision_object.market_narrative.trade_guidance_enabled",
            ),
            "thesis_state": _capture_status(
                present=thesis_state_present, value=thesis.get("state"),
                source="institutional_decision_object.institutional_thesis.state",
            ),
            "conviction_score": _capture_status(
                present=conviction_score_present, value=conviction.get("score"),
                source="institutional_decision_object.conviction.score",
            ),
            "recommendation_action": _capture_status(
                present=recommendation_present, value=recommendation_action,
                source=recommendation_source,
            ),
            "recommendation_state": _capture_status(
                present=recommendation_present, value=recommendation_state,
                source=recommendation_source,
            ),
        },
        "entry_risk_policy_snapshot": risk_policy,
        "source_truth": "FINALIZED_DECISION_TIME_SNAPSHOT_PLUS_ENTRY_RISK_POLICY",
        "historical_policy_inference": False,
        "behavioral_authority": False,
        "execution_authority": False,
        "production_effect": "OBSERVATIONAL_ONLY",
    }

    # Preserve exactly the decision-time fields consumed by effectiveness,
    # dynamic-state calibration and attribution. Avoid persisting raw providers.
    snapshot: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "decision_id": _decision_id(ticker, timestamp, action, direction),
        "timestamp": timestamp,
        "ticker": ticker,
        "session": str(session_state or root.get("session") or "UNKNOWN").upper(),
        "action": action,
        "decision_state": action,
        "direction": thesis_direction if thesis_direction in {"BULLISH", "BEARISH"} else direction,
        "entry_reference": price,
        "confidence": confidence,
        "learning_eligible": learning_eligible,
        "actionable": execution_actionable,
        "execution_actionable": execution_actionable,
        "observational_learning_eligible": observational_eligible and not execution_actionable,
        "observational_only": observational_eligible and not execution_actionable,
        "eligibility_reason": eligibility_reason,
        "eligibility_inputs": {
            "ido_actionable": explicit_actionable, "final_action": action,
            "final_direction": direction, "pre_governance_direction": thesis_direction,
            "entry_reference_available": price is not None,
        },
        "pre_governance_decision": {
            "direction": thesis_direction,
            "thesis_state": thesis.get("state"),
            "current_thesis": thesis.get("current_thesis"),
            "raw_conviction": conviction.get("raw_conviction"),
            "calibrated_conviction": conviction.get("calibrated_conviction"),
            "score": conviction.get("score"),
            "blocking_conditions": conviction.get("blocking_conditions") or [],
            "execution_action_after_governance": action,
            "execution_actionable_after_governance": execution_actionable,
        },
        "setup": ido.get("strategy") or root.get("setup") or root.get("playbook"),
        "institutional_decision_object": ido,
        "trade_horizon_intelligence": _m(root.get("trade_horizon_intelligence")),
        "market_regime": _path(root, "market_regime.regime", "market_regime.state", "market_state.regime", "regime"),
        "gamma_regime": _path(root, "gamma_regime.regime", "gamma_regime.state", "dealer_positioning.gamma_regime", "gamma.regime"),
        "volatility_regime": _path(root, "volatility_regime.regime", "volatility_regime.state", "volatility.regime"),
        "auction_regime": _path(root, "auction_regime.regime", "auction_regime.state", "auction.regime", "auction_intelligence.regime"),
        "apex_release_version": _release_version(),
        "counterfactual_actionability": actionability_capture,
        "dynamic_state": observed_dynamic_state,
        "dynamic_state_policy": observed_dynamic_policy,
        "decision_quality": _m(root.get("decision_quality")),
        "flow_excitation": _m(observed_dynamic_state.get("flow_excitation")),
        "gamma_path": _m(observed_dynamic_state.get("gamma_path")),
        "gamma_term_structure": _m(observed_dynamic_state.get("gamma_term_structure")),
        "residual_pressure": _m(observed_dynamic_state.get("residual_pressure")),
        "event_phase": _m(observed_dynamic_state.get("event_phase")),
        "execution_authority": False,
        "production_effect": "OBSERVATIONAL_ONLY",
    }
    return snapshot


def capture_decision(result: Mapping[str, Any], *, session_state: Optional[str] = None,
                     path: str | Path = DEFAULT_DB) -> Dict[str, Any]:
    """Persist one canonical composed decision. Idempotent by decision_id."""
    snap = build_snapshot(result, session_state=session_state)
    actionability = _m(snap.get("counterfactual_actionability"))
    actionability_ready = bool(
        actionability.get("entry_window_source_present")
        and actionability.get("entry_cutoff_et") not in (None, "")
        and actionability.get("cutoff_passed") is not None
    )
    with _LOCK:
        _RUNTIME["decision_attempts"] += 1
        _RUNTIME["actionability_capture_attempts"] += 1
        if actionability_ready:
            _RUNTIME["actionability_capture_ready"] += 1
        else:
            _RUNTIME["actionability_capture_missing"] += 1
        _RUNTIME["last_actionability_capture_at"] = snap.get("timestamp")
        _RUNTIME["last_actionability_capture_version"] = actionability.get("capture_version")
        _RUNTIME["last_entry_window_source"] = actionability.get("entry_window_source")
        _RUNTIME["last_entry_cutoff_et"] = actionability.get("entry_cutoff_et")
        _RUNTIME["last_cutoff_passed"] = actionability.get("cutoff_passed")
        _RUNTIME["last_actionability_capture_provenance"] = dict(actionability.get("capture_provenance") or {})
    try:
        inserted = bool(record_snapshot(snap, path=path))
        with _LOCK:
            if inserted:
                _RUNTIME["decisions_inserted"] += 1
            else:
                _RUNTIME["decision_duplicates"] += 1
            _RUNTIME["last_decision_at"] = snap["timestamp"]
        _capture_market_memory(result, snap)
        return {"ok": True, "inserted": inserted, "decision_id": snap["decision_id"], "snapshot": snap}
    except Exception as exc:
        with _LOCK:
            _RUNTIME["decision_errors"] += 1
        return {"ok": False, "inserted": False, "decision_id": snap.get("decision_id"), "error": f"{type(exc).__name__}: {exc}"}


def _capture_market_memory(result: Mapping[str, Any], snap: Mapping[str, Any]) -> None:
    """Capture at most one Market Memory observation per session-state/day.

    APEX 69 makes canonical scanner-owned historical capture active by default,
    but it remains observational and can be disabled independently.
    """
    if str(os.getenv("APEX_69_MARKET_MEMORY_CAPTURE_ENABLED", "true")).lower() not in {"1", "true", "yes", "on"}:
        return
    timestamp = str(snap.get("timestamp") or _now())
    key = f"{timestamp[:10]}|{snap.get('ticker')}|{snap.get('session')}"
    with _LOCK:
        if key in _MEMORY_KEYS:
            _RUNTIME["market_memory_duplicates"] += 1
            return
    try:
        from .market_memory_engine_v220 import capture_snapshot
        payload = dict(result or {})
        payload.update({
            "ticker": snap.get("ticker"),
            "session": snap.get("session"),
            "direction": snap.get("direction"),
            "confidence": snap.get("confidence"),
            "price": snap.get("entry_reference"),
            "institutional_decision": {
                "decision": snap.get("action"),
                "bias": snap.get("direction"),
                "confidence": snap.get("confidence"),
                "regime": snap.get("market_regime"),
            },
        })
        out = capture_snapshot(payload, observed_at=timestamp, force=True)
        with _LOCK:
            _MEMORY_KEYS.add(key)
            if out.get("captured"):
                _RUNTIME["market_memory_captures"] += 1
            else:
                _RUNTIME["market_memory_duplicates"] += 1
    except Exception:
        with _LOCK:
            _RUNTIME["market_memory_errors"] += 1


def sample_price(ticker: str, price: Any, *, observed_at: Optional[str] = None,
                 path: str | Path = DEFAULT_DB) -> Dict[str, Any]:
    with _LOCK:
        _RUNTIME["price_attempts"] += 1
    try:
        written = bool(record_price(ticker, price, observed_at=observed_at, path=path))
        with _LOCK:
            if written:
                _RUNTIME["prices_written"] += 1
                _RUNTIME["last_price_at"] = observed_at or _now()
        return {"ok": written, "written": written}
    except Exception as exc:
        with _LOCK:
            _RUNTIME["price_errors"] += 1
        return {"ok": False, "written": False, "error": f"{type(exc).__name__}: {exc}"}


def grade(*, path: str | Path = DEFAULT_DB) -> Dict[str, Any]:
    with _LOCK:
        _RUNTIME["grader_runs"] += 1
    try:
        out = run_grader(path=path)
        with _LOCK:
            _RUNTIME["last_grade_at"] = _now()
            _RUNTIME["last_grade_result"] = out
        return out
    except Exception as exc:
        with _LOCK:
            _RUNTIME["grader_errors"] += 1
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def actionability_capture_audit(*, path: str | Path = DEFAULT_DB, limit: int = 100) -> Dict[str, Any]:
    """Inspect persisted decision-time actionability before grading/trigger linkage.

    This closes the observability gap where counterfactual qualification could report
    zero current-release rows simply because new decisions had not yet graded. The
    audit reads the canonical decision ledger directly and never mutates evidence.
    """
    resolved = Path(path)
    base = {
        "ok": True,
        "version": VERSION,
        "schema_version": "apex.live_actionability_capture_audit.v1",
        "production_effect": "OBSERVATIONAL_ONLY",
        "behavioral_authority": False,
        "execution_authority": False,
        "historical_policy_inference": False,
        "current_release": VERSION,
    }
    if not resolved.exists():
        return {**base, "status": "WAITING_FOR_EVIDENCE_DB", "sample_size": 0,
                "current_release_rows": 0, "current_release_entry_window_ready": 0,
                "current_release_entry_window_ready_pct": None, "recent_decisions": []}
    bounded = max(1, min(int(limit or 100), 500))
    rows: list[Dict[str, Any]] = []
    parse_errors: list[Dict[str, str]] = []
    try:
        with canonical_connect(resolved, read_only=True, timeout=4) as conn:
            has_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='decisions'"
            ).fetchone()
            if not has_table:
                return {**base, "status": "WAITING_FOR_DECISIONS_TABLE", "sample_size": 0,
                        "current_release_rows": 0, "current_release_entry_window_ready": 0,
                        "current_release_entry_window_ready_pct": None, "recent_decisions": []}
            raw_rows = conn.execute(
                """SELECT decision_id,observed_at,ticker,session,direction,action,status,snapshot_json
                   FROM decisions ORDER BY observed_at DESC LIMIT ?""",
                (bounded,),
            ).fetchall()
            grade_ids = {
                str(r["decision_id"]) for r in conn.execute(
                    "SELECT decision_id FROM grading_results WHERE decision_id IN (SELECT decision_id FROM decisions ORDER BY observed_at DESC LIMIT ?)",
                    (bounded,),
                ).fetchall()
            }
        for raw in raw_rows:
            did = str(raw["decision_id"] or "")
            try:
                parsed = json.loads(raw["snapshot_json"] or "{}")
                snap = dict(parsed) if isinstance(parsed, Mapping) else {}
                actionability = _m(snap.get("counterfactual_actionability"))
                release = str(snap.get("apex_release_version") or snap.get("version") or "UNKNOWN")
                source_present = bool(actionability.get("entry_window_source_present"))
                ready = bool(
                    source_present
                    and actionability.get("entry_cutoff_et") not in (None, "")
                    and actionability.get("cutoff_passed") is not None
                )
                if not actionability:
                    stage = "DECISION_PERSISTED_ACTIONABILITY_CAPTURE_MISSING"
                elif ready:
                    stage = "DECISION_PERSISTED_ENTRY_WINDOW_READY"
                elif source_present:
                    stage = "DECISION_PERSISTED_ENTRY_WINDOW_PARTIAL"
                else:
                    stage = "DECISION_PERSISTED_ENTRY_WINDOW_SOURCE_MISSING"
                rows.append({
                    "decision_id": did,
                    "observed_at": raw["observed_at"],
                    "ticker": raw["ticker"],
                    "session": raw["session"],
                    "direction": raw["direction"],
                    "action": raw["action"],
                    "decision_status": raw["status"],
                    "release_version": release,
                    "capture_version": actionability.get("capture_version"),
                    "capture_schema_version": actionability.get("schema_version"),
                    "entry_window_source": actionability.get("entry_window_source") or "UNAVAILABLE",
                    "entry_window_source_present": source_present,
                    "entry_cutoff_et": actionability.get("entry_cutoff_et"),
                    "cutoff_passed": actionability.get("cutoff_passed"),
                    "entry_window_authorized": actionability.get("entry_window_authorized"),
                    "capture_provenance": dict(actionability.get("capture_provenance") or {}),
                    "grade_present": did in grade_ids,
                    "lifecycle_stage": stage,
                })
            except Exception as exc:
                parse_errors.append({"decision_id": did, "error": f"{type(exc).__name__}: {exc}"})
    except Exception as exc:
        return {**base, "ok": False, "status": "EVIDENCE_READ_ERROR",
                "error": f"{type(exc).__name__}: {exc}", "recent_decisions": []}

    current = [r for r in rows if r.get("release_version") == VERSION]
    current_ready = [r for r in current if r.get("lifecycle_stage") == "DECISION_PERSISTED_ENTRY_WINDOW_READY"]
    source_counts: Dict[str, int] = {}
    stage_counts: Dict[str, int] = {}
    capture_versions: Dict[str, int] = {}
    for row in rows:
        source = str(row.get("entry_window_source") or "UNAVAILABLE")
        source_counts[source] = source_counts.get(source, 0) + 1
        stage = str(row.get("lifecycle_stage") or "UNKNOWN")
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
        cv = str(row.get("capture_version") or "LEGACY_OR_UNKNOWN")
        capture_versions[cv] = capture_versions.get(cv, 0) + 1
    if not current:
        status = "WAITING_FOR_CURRENT_RELEASE_DECISION"
    elif len(current_ready) == len(current):
        status = "CURRENT_RELEASE_ENTRY_WINDOW_READY"
    elif current_ready:
        status = "CURRENT_RELEASE_ENTRY_WINDOW_PARTIAL"
    else:
        status = "CURRENT_RELEASE_ENTRY_WINDOW_NOT_READY"
    return {
        **base,
        "status": status,
        "sample_size": len(rows),
        "parse_error_count": len(parse_errors),
        "parse_errors": parse_errors[:20],
        "capture_version_counts": capture_versions,
        "entry_window_source_counts": source_counts,
        "lifecycle_stage_counts": stage_counts,
        "latest_decision_observed_at": rows[0].get("observed_at") if rows else None,
        "latest_decision_release_version": rows[0].get("release_version") if rows else None,
        "current_release_rows": len(current),
        "current_release_entry_window_ready": len(current_ready),
        "current_release_entry_window_ready_pct": (
            round(100.0 * len(current_ready) / len(current), 2) if current else None
        ),
        "current_release_capture_hook_seen": bool(current),
        "current_release_recent_decisions": current[:20],
        "recent_decisions": rows[:50],
        "interpretation": (
            "This audit reads canonical decisions before grading and trigger linkage, so a zero counterfactual current-release row count can be separated from a missing live capture hook."
        ),
    }


def runtime_status(*, path: str | Path = DEFAULT_DB) -> Dict[str, Any]:
    try:
        ready = readiness(path)
    except Exception as exc:
        ready = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    with _LOCK:
        runtime = dict(_RUNTIME)
    try:
        live_capture = actionability_capture_audit(path=path, limit=50)
    except Exception as exc:
        live_capture = {"ok": False, "status": "AUDIT_ERROR", "error": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": bool(ready.get("ok", False)),
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "readiness": ready,
        "runtime": runtime,
        "live_actionability_capture_audit": live_capture,
        "guardrails": {
            "backfills_history": False,
            "creates_synthetic_evidence": False,
            "changes_trade_decisions": False,
            "changes_execution_authority": False,
            "execution_authority": False,
        },
    }
