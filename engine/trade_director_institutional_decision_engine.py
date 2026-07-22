"""APEX Trade Director Phase 20 — Institutional Decision Engine.

Turns Phase 19 committee intelligence into a governed, deterministic decision
lifecycle. Cached/advisory only: no providers, brokers, order placement, startup
workers, or autonomous execution.
"""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Dict, Mapping, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _u(v: Any) -> str:
    return str(v or "").strip().upper()

def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default

def _m(v: Any) -> Mapping[str, Any]:
    return v if isinstance(v, Mapping) else {}

def _stable_id(parts: Mapping[str, Any]) -> str:
    raw = "|".join(f"{k}={parts[k]}" for k in sorted(parts))
    return "D20-" + sha256(raw.encode("utf-8")).hexdigest()[:16].upper()


def build_institutional_decision_engine(context: Optional[Mapping[str, Any]], prior: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    c = dict(context or {})
    p19 = _m(c.get("decision_intelligence"))
    session = _m(c.get("session_intelligence")); session_state = _m(session.get("session"))
    strategy = _m(c.get("strategy_orchestration")); options = _m(c.get("options_intelligence"))
    execution = _m(c.get("execution_desk")); mtf = _m(c.get("multi_timeframe_intelligence"))
    flow = _m(c.get("flow_intelligence")); position = _m(c.get("position"))

    committee_state = _u(p19.get("decision_state")) or "WATCH"
    action = _u(p19.get("recommended_action")) or committee_state
    direction = _u(p19.get("dominant_direction")) or "NEUTRAL"
    consensus = _f(p19.get("consensus_score")); confidence = _f(p19.get("confidence"))
    coverage = _f(p19.get("evidence_coverage_pct"))
    session_mode = _u(session_state.get("mode"))
    strategy_gate = _u(strategy.get("decision_gate"))
    option_gate = _u(options.get("decision_gate"))
    execution_gate = _u(execution.get("decision_gate") or execution.get("gate"))
    mtf_gate = _u(mtf.get("decision_gate")); flow_gate = _u(flow.get("decision_gate"))

    blockers = []
    if session_mode == "STOP_TRADING": blockers.append("Session Intelligence has locked trading.")
    if committee_state == "STAND_DOWN": blockers.append("Phase 19 committee requires STAND_DOWN.")
    if strategy_gate == "STAND_DOWN": blockers.append("Strategy Orchestration requires STAND_DOWN.")
    if execution_gate == "BLOCKED": blockers.append("Execution Desk is blocked.")
    if mtf_gate == "STAND_DOWN" or flow_gate == "STAND_DOWN": blockers.append("An upstream intelligence engine requires STAND_DOWN.")

    requirements = [
        ("Committee direction is actionable", committee_state in ("BUY", "STRONG_BUY")),
        ("Consensus meets threshold", consensus >= 58),
        ("Confidence meets threshold", confidence >= 55),
        ("Evidence coverage is sufficient", coverage >= 55),
        ("Session permits risk", session_mode not in ("STOP_TRADING", "")),
        ("Strategy is selected", strategy_gate in ("STRATEGY_SELECTED", "WAIT_FOR_CONFIRMATION")),
        ("Verified contract exists", option_gate == "CONTRACT_CANDIDATE_SELECTED"),
        ("Execution desk is ready", execution_gate in ("READY_FOR_PHASE10_PREVIEW", "READY_FOR_USER_CONFIRMATION", "READY")),
        ("Timeframes are aligned", mtf_gate == "ALIGNED"),
        ("Flow is confirmatory", flow_gate == "INSTITUTIONAL_CONFIRMATION"),
    ]
    checklist = [{"name": n, "passed": bool(ok)} for n, ok in requirements]
    passed = sum(1 for _, ok in requirements if ok)

    invalidations = []
    if direction == "BULLISH":
        invalidations += ["Higher-timeframe bias turns bearish", "Institutional flow turns bearish or conflicted", "Phase 19 falls below WATCH"]
    elif direction == "BEARISH":
        invalidations += ["Higher-timeframe bias turns bullish", "Institutional flow turns bullish or conflicted", "Phase 19 falls below WATCH"]
    else:
        invalidations.append("Directional evidence remains neutral")
    invalidations += ["Session changes to STOP_TRADING", "Execution Desk becomes BLOCKED", "Risk or confirmation gate fails"]

    if blockers:
        state = "DECISION_BLOCKED"
    elif committee_state not in ("BUY", "STRONG_BUY"):
        state = "OBSERVE"
    elif passed < 7:
        state = "AWAITING_VALIDATION"
    elif passed < len(requirements):
        state = "CONDITIONALLY_AUTHORIZED"
    else:
        state = "AUTHORIZED_FOR_PREVIEW"

    prior_map = _m(prior)
    prior_state = _u(prior_map.get("authorization_state"))
    # Less-defensive promotion requires stable repeat evidence; defensive moves are immediate.
    promotion_states = {"AUTHORIZED_FOR_PREVIEW", "CONDITIONALLY_AUTHORIZED"}
    stability = "STABLE"
    if state in promotion_states and prior_state and prior_state not in promotion_states:
        state = "AWAITING_VALIDATION"
        stability = "PROMOTION_CONFIRMATION_REQUIRED"
    elif prior_state and prior_state != state:
        stability = "DEFENSIVE_CHANGE_IMMEDIATE" if state in ("DECISION_BLOCKED", "OBSERVE") else "STATE_CHANGED"

    contract = _m(options.get("best_contract") or options.get("selected_contract"))
    plan = _m(execution.get("order_plan"))
    decision_id = _stable_id({
        "action": action, "direction": direction, "contract": contract.get("symbol") or contract.get("strike") or "NONE",
        "limit": plan.get("limit_price") or "NONE", "state": state, "consensus": round(consensus, 1)
    })

    authorization = {
        "decision_id": decision_id,
        "authorization_state": state,
        "authorized_action": action if state in ("AUTHORIZED_FOR_PREVIEW", "CONDITIONALLY_AUTHORIZED") else "NONE",
        "direction": direction,
        "contract_symbol": contract.get("symbol"),
        "quantity": plan.get("quantity"),
        "limit_price": plan.get("limit_price"),
        "expires_on_material_change": True,
        "broker_execution_enabled": False,
        "requires_phase10_exact_confirmation": True,
    }

    narrative = (
        f"Phase 20 evaluated {passed} of {len(requirements)} authorization conditions. "
        f"The Phase 19 committee is {committee_state} with {consensus:.1f} consensus and {confidence:.1f}% confidence. "
    )
    if blockers:
        narrative += blockers[0]
    elif state == "AUTHORIZED_FOR_PREVIEW":
        narrative += "The decision is authorized only to proceed to broker preview and exact user confirmation."
    elif state == "CONDITIONALLY_AUTHORIZED":
        narrative += "The setup is actionable but one or more secondary confirmations remain incomplete."
    else:
        narrative += "APEX will continue observing until validation improves."

    return {
        "version": "PHASE_20", "as_of": _now(), "mode": "GOVERNED_DECISION_LIFECYCLE",
        "authorization_state": state, "decision_id": decision_id,
        "committee_state": committee_state, "recommended_action": action,
        "dominant_direction": direction, "consensus_score": round(consensus, 1),
        "confidence": round(confidence, 1), "evidence_coverage_pct": round(coverage, 1),
        "authorization": authorization, "authorization_checklist": checklist,
        "checklist_passed": passed, "checklist_total": len(requirements),
        "hard_blockers": blockers, "invalidation_rules": invalidations,
        "stability": {"state": stability, "prior_authorization_state": prior_state or None,
                      "defensive_changes": "IMMEDIATE", "promotions": "REQUIRE_STABLE_REPEAT"},
        "decision_narrative": narrative,
        "accountability": {"persist_decision": True, "capture_inputs": True, "capture_outcome": True,
                           "autonomous_execution": False},
        "safety_note": "Advisory governance only. Phase 20 cannot place orders, contact a broker, bypass Phase 9 risk controls, bypass Phase 10 exact confirmation, weaken Phase 16 execution safeguards, or override upstream STAND_DOWN authority."
    }
