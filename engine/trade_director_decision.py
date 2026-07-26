"""engine/trade_director_decision.py — consolidated Trade Director decision stack.

Consolidation Sprint 2 merge of three modules that shared one concern — how the
Trade Director reads, scores, and grades a decision:
  * Phase 19 build_decision_intelligence      (engine consensus voting)
  * Phase 20 build_institutional_decision_engine (stable decision object + id)
  * Phase 38 build_decision_quality / build_flow_participation (quality grading)
Public APIs are unchanged; private helpers deduplicated (they were byte-identical).
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Dict, Iterable, Mapping, Optional, List, Tuple

QUALITY_VERSION = "38.0"
VERSION = QUALITY_VERSION  # kept for callers importing VERSION from the quality module

# ── Phase 19: decision intelligence (engine consensus) ──────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _f(v: Any, default: float = 0.0) -> float:
    try: return float(v)
    except (TypeError, ValueError): return default

def _u(v: Any) -> str:
    return str(v or "").strip().upper()

def _m(v: Any) -> Mapping[str, Any]:
    return v if isinstance(v, Mapping) else {}

def _direction(value: Any) -> str:
    x = _u(value)
    if any(k in x for k in ("BULL", "CALL", "UP", "LONG")): return "BULLISH"
    if any(k in x for k in ("BEAR", "PUT", "DOWN", "SHORT")): return "BEARISH"
    return "NEUTRAL"

def _vote(name: str, phase: str, direction: str, confidence: float, weight: float,
          gate: str = "", detail: str = "", available: bool = True) -> Dict[str, Any]:
    confidence = max(0.0, min(100.0, confidence))
    return {"engine": name, "phase": phase, "direction": direction, "confidence": round(confidence,1),
            "weight": weight, "gate": gate or "AVAILABLE", "detail": detail, "available": bool(available)}

def build_decision_intelligence(context: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    c = dict(context or {})
    session = _m(c.get("session_intelligence")); market = _m(c.get("market_memory"))
    cross = _m(c.get("cross_asset_intelligence")); strategy = _m(c.get("strategy_orchestration"))
    options = _m(c.get("options_intelligence")); execution = _m(c.get("execution_desk"))
    mtf = _m(c.get("multi_timeframe_intelligence")); flow = _m(c.get("flow_intelligence"))

    session_state = _m(session.get("session")); session_mode = _u(session_state.get("mode"))
    strategy_gate = _u(strategy.get("decision_gate")); mtf_gate = _u(mtf.get("decision_gate"))
    flow_gate = _u(flow.get("decision_gate")); option_gate = _u(options.get("decision_gate"))
    execution_gate = _u(execution.get("decision_gate") or execution.get("gate"))

    votes: List[Dict[str, Any]] = []
    votes.append(_vote("Session Intelligence","11", _direction(session.get("bias") or session_state.get("bias")),
                       _f(session.get("confidence") or session.get("institutional_scorecard",{}).get("overall"),50), 0.10,
                       session_mode, session_state.get("mode_reason",""), bool(session)))
    planner = _m(market.get("predictive_session_planner"))
    votes.append(_vote("Market Memory","12", _direction(planner.get("direction") or planner.get("expected_path") or planner.get("preferred_playbook")),
                       _f(planner.get("confidence"),45), 0.10, planner.get("expected_session_type",""),
                       "Historical similarity and calibrated playbook evidence", bool(market)))
    votes.append(_vote("Cross-Asset","13", _direction(cross.get("cross_asset_bias") or cross.get("bias")),
                       _f(cross.get("confidence"),45), 0.12, cross.get("regime",""),
                       f"SPX confirmation {cross.get('spx_confirmation_score','--')}", bool(cross)))
    votes.append(_vote("Strategy Orchestration","14", _direction(strategy.get("direction") or strategy.get("selected_strategy")),
                       _f(strategy.get("confidence") or strategy.get("opportunity_score"),50), 0.14, strategy_gate,
                       str(strategy.get("rationale") or strategy.get("reason") or ""), bool(strategy)))
    votes.append(_vote("Options Intelligence","15", _direction(options.get("direction") or options.get("option_side") or options.get("selected_contract",{}).get("side")),
                       _f(options.get("confidence") or options.get("contract_score"),50), 0.08, option_gate,
                       "Contract quality and liquidity readiness", bool(options)))
    votes.append(_vote("Execution Desk","16", "NEUTRAL", _f(execution.get("execution_quality_score"),50), 0.06,
                       execution_gate, "Execution quality is a readiness vote, not directional evidence", bool(execution)))
    votes.append(_vote("Multi-Timeframe","17", _direction(mtf.get("dominant_direction") or mtf.get("higher_timeframe_direction")),
                       _f(mtf.get("confidence") or mtf.get("alignment_score"),50), 0.20, mtf_gate,
                       str(mtf.get("entry_timing") or ""), bool(mtf)))
    votes.append(_vote("Institutional Flow","18", _direction(flow.get("institutional_bias")),
                       _f(flow.get("confidence") or flow.get("institutional_score"),50), 0.20, flow_gate,
                       str(flow.get("interpretation") or ""), bool(flow)))

    active = [v for v in votes if v["available"]]
    coverage = sum(v["weight"] for v in active)
    bull = sum(v["weight"] * v["confidence"] for v in active if v["direction"] == "BULLISH")
    bear = sum(v["weight"] * v["confidence"] for v in active if v["direction"] == "BEARISH")
    neutral = sum(v["weight"] * v["confidence"] for v in active if v["direction"] == "NEUTRAL")
    denom = max(1.0, bull + bear + neutral)
    bull_prob = 100.0 * bull / denom; bear_prob = 100.0 * bear / denom
    neutral_prob = max(0.0, 100.0 - bull_prob - bear_prob)
    dominant = "BULLISH" if bull_prob >= bear_prob + 8 else "BEARISH" if bear_prob >= bull_prob + 8 else "NEUTRAL"
    directional_strength = abs(bull_prob - bear_prob)
    evidence_quality = min(100.0, coverage * 100)
    consensus = min(100.0, directional_strength * .65 + evidence_quality * .35)

    conflicts = []
    dirs = {v["engine"]: v["direction"] for v in active if v["direction"] != "NEUTRAL"}
    if len(set(dirs.values())) > 1:
        conflicts.append("Directional engines disagree; higher-weight timeframe and institutional-flow evidence receive priority.")
    if mtf_gate in ("TIMEFRAME_CONFLICT","WAIT_FOR_ALIGNMENT"):
        conflicts.append("Multi-timeframe hierarchy is not fully aligned.")
    if flow_gate in ("FLOW_CONFLICT","MIXED_FLOW"):
        conflicts.append("Institutional flow does not provide clean confirmation.")
    if cross.get("divergences"):
        conflicts.append("Cross-asset divergence reduces conviction.")

    hard_blockers = []
    if session_mode == "STOP_TRADING": hard_blockers.append("Session Intelligence has locked trading for the session.")
    if strategy_gate == "STAND_DOWN": hard_blockers.append("Strategy Orchestration requires STAND_DOWN.")
    if mtf_gate == "STAND_DOWN" or flow_gate == "STAND_DOWN": hard_blockers.append("An upstream intelligence engine requires STAND_DOWN.")
    if execution_gate == "BLOCKED": hard_blockers.append("Execution Desk is blocked.")

    required = [
        ("Session permits trading", session_mode not in ("STOP_TRADING","")),
        ("Strategy is actionable", strategy_gate in ("STRATEGY_SELECTED","WAIT_FOR_CONFIRMATION")),
        ("Timeframes are aligned", mtf_gate == "ALIGNED"),
        ("Institutional flow confirms", flow_gate == "INSTITUTIONAL_CONFIRMATION"),
        ("Contract candidate exists", option_gate == "CONTRACT_CANDIDATE_SELECTED"),
        ("Execution plan is ready", execution_gate in ("READY_FOR_PHASE10_PREVIEW","READY_FOR_USER_CONFIRMATION","READY")),
    ]
    checklist = [{"name": n, "passed": p} for n,p in required]
    passed = sum(1 for _,p in required if p)

    if hard_blockers:
        state = "STAND_DOWN"
    elif coverage < .55:
        state = "WATCH"
    elif flow_gate in ("FLOW_CONFLICT", "MIXED_FLOW") or mtf_gate in ("TIMEFRAME_CONFLICT", "WAIT_FOR_ALIGNMENT"):
        state = "WATCH"
    elif conflicts and consensus < 62:
        state = "WATCH"
    elif dominant == "NEUTRAL":
        state = "WATCH"
    elif consensus >= 76 and passed >= 4:
        state = "STRONG_BUY"
    elif consensus >= 58 and passed >= 3:
        state = "BUY"
    elif c.get("position") and (consensus < 38 or dominant == "NEUTRAL"):
        state = "REDUCE_RISK"
    else:
        state = "WATCH"

    # Never allow a bullish label to imply direction for bearish setups.
    action = state
    if state in ("BUY","STRONG_BUY"):
        action = f"{state}_{'CALL' if dominant == 'BULLISH' else 'PUT'}"

    calibration = _m(market.get("confidence_calibration"))
    calibrated = _f(calibration.get("calibrated_confidence"), consensus)
    final_conf = min(consensus, calibrated + 8) if calibration else consensus
    final_conf = max(0.0, final_conf - min(24, len(conflicts)*7))

    narrative_parts = []
    if dominant != "NEUTRAL": narrative_parts.append(f"The weighted committee favors {dominant.lower()} exposure.")
    else: narrative_parts.append("The committee does not have a decisive directional edge.")
    narrative_parts.append(f"Evidence coverage is {evidence_quality:.0f}% and {passed} of {len(required)} institutional conditions are satisfied.")
    if conflicts: narrative_parts.append(conflicts[0])
    if hard_blockers: narrative_parts.append(hard_blockers[0])

    return {
        "version":"PHASE_19", "as_of":_now(), "mode":"CACHED_ONLY_DECISION_FUSION",
        "decision_state":state, "recommended_action":action, "dominant_direction":dominant,
        "consensus_score":round(consensus,1), "confidence":round(final_conf,1),
        "evidence_coverage_pct":round(evidence_quality,1),
        "scenario_probabilities":{"bullish":round(bull_prob,1),"bearish":round(bear_prob,1),"neutral":round(neutral_prob,1)},
        "engine_votes":votes, "conflicts":conflicts, "hard_blockers":hard_blockers,
        "institutional_checklist":checklist, "checklist_passed":passed, "checklist_total":len(required),
        "decision_narrative":" ".join(narrative_parts),
        "stability_policy":{"defensive_changes":"IMMEDIATE","less_defensive_changes":"REQUIRE_CONFIRMATION","minor_fluctuations":"HOLD_PREVIOUS_STATE"},
        "trade_director_effect":{"health_adjustment": 6 if state in ("BUY","STRONG_BUY") else -12 if state in ("REDUCE_RISK","EXIT","STAND_DOWN") else 0,
                                 "sizing_posture":"NORMAL" if state=="STRONG_BUY" else "REDUCED" if state in ("BUY","WATCH") else "ZERO"},
        "safety_note":"Advisory only. Phase 19 cannot override session lockouts, risk limits, exact confirmation, execution safeguards, or upstream STAND_DOWN authority."
    }


# ── Phase 20: institutional decision engine (stable decision object) ────────

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


# ── Phase 38: decision quality + flow participation grading ─────────────────



def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _num(v: Any, default: float = 0.0) -> float:
    try:
        n = float(v)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def _upper(v: Any) -> str:
    return str(v or "").strip().upper().replace(" ", "_")


def _direction(v: Any) -> str:
    t = _upper(v)
    if any(x in t for x in ("BULL", "CALL", "UP", "LONG", "BUY")):
        return "BULLISH"
    if any(x in t for x in ("BEAR", "PUT", "DOWN", "SHORT", "SELL")):
        return "BEARISH"
    return "NEUTRAL"


def _iter_flow_rows(node: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(node, Mapping):
        looks_like = any(k in node for k in ("premium", "notional", "dollar_value")) and any(
            k in node for k in ("size", "quantity", "contracts", "strike")
        )
        if looks_like:
            yield node
        for value in node.values():
            if isinstance(value, (Mapping, list, tuple)):
                yield from _iter_flow_rows(value)
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from _iter_flow_rows(item)


def build_flow_participation(snapshot: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Describe participation quality without equating contract count with conviction."""
    s = dict(snapshot or {})
    rows = list(_iter_flow_rows(s.get("flow") or s.get("flow_tape") or s.get("options_flow") or s))[:2500]
    if not rows:
        return {
            "status": "UNAVAILABLE", "event_count": 0, "classified_premium": 0.0,
            "delta_adjusted_notional": None, "small_lot_share_pct": None,
            "block_share_pct": None, "strike_concentration_pct": None,
            "opening_share_pct": None, "participant_mix": "UNKNOWN",
            "explanation": "No normalized option-flow events were available.",
        }

    total_premium = 0.0
    delta_notional = 0.0
    small_premium = 0.0
    block_premium = 0.0
    opening_premium = 0.0
    strike_premium: Dict[str, float] = defaultdict(float)
    usable = 0

    for row in rows:
        premium = _num(row.get("premium") or row.get("notional") or row.get("dollar_value"))
        size = _num(row.get("size") or row.get("quantity") or row.get("contracts"))
        if premium <= 0:
            premium = _num(row.get("price") or row.get("fill_price")) * size * 100.0
        if premium <= 0:
            continue
        usable += 1
        total_premium += premium
        delta = abs(_num(row.get("delta"), 0.0))
        if delta > 1.0:
            delta /= 100.0
        delta_notional += premium * min(1.0, delta) if delta else 0.0
        if size and size <= 10:
            small_premium += premium
        kind = _upper(row.get("type") or row.get("trade_type") or row.get("condition"))
        if "BLOCK" in kind or size >= 100:
            block_premium += premium
        effect = _upper(row.get("position_effect") or row.get("open_close") or row.get("intent"))
        if "OPEN" in effect:
            opening_premium += premium
        strike = row.get("strike")
        if strike is not None:
            strike_premium[str(strike)] += premium

    if usable == 0 or total_premium <= 0:
        return {"status": "UNAVAILABLE", "event_count": 0, "classified_premium": 0.0,
                "explanation": "Flow rows existed but none had usable premium or size."}

    top3 = sum(sorted(strike_premium.values(), reverse=True)[:3])
    small_share = small_premium / total_premium * 100.0
    block_share = block_premium / total_premium * 100.0
    concentration = top3 / total_premium * 100.0 if strike_premium else 0.0
    opening_share = opening_premium / total_premium * 100.0
    if block_share >= 35:
        mix = "BLOCK_LED"
    elif small_share >= 55:
        mix = "SMALL_LOT_LED"
    else:
        mix = "MIXED_PARTICIPATION"

    return {
        "status": "READY",
        "event_count": usable,
        "classified_premium": round(total_premium, 2),
        "delta_adjusted_notional": round(delta_notional, 2) if delta_notional else None,
        "small_lot_share_pct": round(small_share, 1),
        "block_share_pct": round(block_share, 1),
        "strike_concentration_pct": round(concentration, 1),
        "opening_share_pct": round(opening_share, 1),
        "participant_mix": mix,
        "explanation": (
            "Participation is described by premium, delta exposure, trade size, opening intent, "
            "and strike concentration; raw contracts are not treated as institutional conviction."
        ),
    }


def _policy_metrics(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    p = snapshot.get("policy_metrics") or snapshot.get("alert_metrics") or {}
    if not isinstance(p, Mapping):
        p = {}
    precision = _num(p.get("actionable_precision_pct") or p.get("precision_pct"), -1)
    slippage = _num(p.get("avg_slippage_pct") or p.get("slippage_pct"), -1)
    latency = _num(p.get("alert_latency_ms") or p.get("latency_ms"), -1)
    mae = _num(p.get("mae_pct") or p.get("max_adverse_excursion_pct"), -1)
    next_fill = _num(p.get("next_executable_return_pct") or p.get("next_fill_return_pct"), -999)
    available = any(x >= 0 for x in (precision, slippage, latency, mae)) or next_fill > -999
    return {
        "status": "READY" if available else "COLLECTING",
        "actionable_precision_pct": None if precision < 0 else round(precision, 2),
        "avg_slippage_pct": None if slippage < 0 else round(slippage, 3),
        "alert_latency_ms": None if latency < 0 else round(latency, 1),
        "mae_pct": None if mae < 0 else round(mae, 3),
        "next_executable_return_pct": None if next_fill <= -999 else round(next_fill, 3),
        "grading_rule": "Grade prediction quality separately from executable policy quality.",
    }


def build_decision_quality(snapshot: Optional[Mapping[str, Any]], prior_state: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    s = dict(snapshot or {})
    direction = _direction(s.get("direction") or s.get("bias") or s.get("consensus_label"))
    confidence = _num(s.get("confidence") or s.get("ici") or s.get("institutional_confidence"))
    execution = _num(s.get("execution_score") or (s.get("execution") or {}).get("score"))
    position_quality = _num(s.get("position_quality") or (s.get("execution") or {}).get("position_quality"))
    freshness_ok = not bool(s.get("stale")) and bool(s.get("data_fresh", True))
    market_open = bool(s.get("market_open", True))
    liquidity = _upper(s.get("option_liquidity_state") or s.get("liquidity_state") or "UNKNOWN")
    recommendation = _upper(s.get("recommendation") or s.get("decision") or "WAIT")

    entry_threshold = _num(s.get("entry_confidence_threshold"), 80.0)
    exit_threshold = _num(s.get("exit_confidence_threshold"), max(0.0, entry_threshold - 8.0))
    active = bool((prior_state or {}).get("active") or s.get("position_active") or "HOLD" in recommendation)
    applied_threshold = exit_threshold if active else entry_threshold
    boundary_margin = confidence - applied_threshold

    blockers = []
    if not market_open:
        blockers.append("MARKET_CLOSED")
    if not freshness_ok:
        blockers.append("STALE_OR_MISSING_DATA")
    if direction == "NEUTRAL":
        blockers.append("NO_DIRECTIONAL_CONSENSUS")
    if liquidity in {"POOR", "WIDE", "UNAVAILABLE", "FAILED"}:
        blockers.append("LIQUIDITY_NOT_ELIGIBLE")
    if confidence < applied_threshold:
        blockers.append("CONFIDENCE_BELOW_DECISION_BOUNDARY")
    if execution and execution < 70:
        blockers.append("EXECUTION_QUALITY_BELOW_MINIMUM")
    if position_quality and position_quality < 70:
        blockers.append("POSITION_QUALITY_BELOW_MINIMUM")

    participation = build_flow_participation(s)
    # Do not let raw-volume participation independently authorize an alert.
    if participation.get("status") == "READY":
        if participation.get("small_lot_share_pct", 0) >= 70 and participation.get("block_share_pct", 0) < 10:
            blockers.append("SMALL_LOT_DOMINATED_FLOW")
        if participation.get("strike_concentration_pct", 0) < 20:
            blockers.append("FLOW_TOO_DISPERSED")

    alert_eligible = not blockers
    if alert_eligible and boundary_margin < 5:
        alert_state = "WATCH_ONLY"
        alert_eligible = False
        blockers.append("INSUFFICIENT_BOUNDARY_MARGIN")
    elif alert_eligible:
        alert_state = "ELIGIBLE"
    else:
        alert_state = "SUPPRESSED"

    return {
        "version": VERSION,
        "generated_at": _now(),
        "status": "READY" if freshness_ok else "DEGRADED",
        "direction": direction,
        "recommendation": recommendation,
        "confidence": round(confidence, 1),
        "decision_boundary": {
            "active_state": active,
            "entry_threshold": entry_threshold,
            "exit_threshold": exit_threshold,
            "applied_threshold": applied_threshold,
            "margin_points": round(boundary_margin, 1),
            "hysteresis_points": round(entry_threshold - exit_threshold, 1),
            "next_state_requirement": (
                f"Confidence must improve by {abs(boundary_margin):.1f} points to reach the boundary."
                if boundary_margin < 0 else
                f"Confidence is {boundary_margin:.1f} points above the active boundary."
            ),
        },
        "alert_quality": {
            "state": alert_state,
            "alert_eligible": alert_eligible,
            "blocking_conditions": blockers,
            "abstention_is_valid": True,
            "explanation": (
                "Alerts are gated by executable decision quality, not directional prediction or raw volume alone."
            ),
        },
        "flow_participation": participation,
        "policy_quality": _policy_metrics(s),
        "counterfactuals": [
            {"change": "confidence", "required": round(max(0.0, applied_threshold + 5.0 - confidence), 1),
             "effect": "Would clear the minimum decision-boundary margin."},
            {"change": "data_freshness", "required": "FRESH", "effect": "Removes stale-data suppression."},
            {"change": "liquidity", "required": "NORMAL_OR_BETTER", "effect": "Removes execution-liquidity suppression."},
        ],
        "governance": {
            "advisory_only": True,
            "no_trade_call": True,
            "next_executable_price_required_for_grading": True,
            "raw_volume_not_conviction": True,
        },
    }
