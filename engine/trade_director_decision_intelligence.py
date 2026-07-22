"""APEX Trade Director Phase 19 — Institutional Decision Intelligence.

Pure, cached-only evidence fusion.  The module never fetches providers or brokers and
never weakens upstream stand-down, session lockout, risk, or confirmation controls.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, List, Tuple


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
