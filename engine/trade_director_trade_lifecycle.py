"""APEX Trade Director Phase 21 — Institutional Trade Lifecycle Engine.

Consumes the coordinated Phase 11–20 decision package and produces one governed
trade-management recommendation. Advisory only: no broker/provider calls, no
order mutation, no background workers, and no startup side effects.
"""
from __future__ import annotations
from hashlib import sha256
from typing import Any, Dict, Mapping, Optional

from engine.trade_director_lifecycle_contracts import as_mapping, normalize_trade_context, utc_now_iso


def _u(value: Any) -> str:
    return str(value or "").strip().upper()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _stable_id(parts: Mapping[str, Any]) -> str:
    raw = "|".join(f"{key}={parts[key]}" for key in sorted(parts))
    return "L21-" + sha256(raw.encode("utf-8")).hexdigest()[:16].upper()


def _position_open(position: Mapping[str, Any]) -> bool:
    status = _u(position.get("status") or position.get("position_status"))
    qty = _i(position.get("quantity") or position.get("contracts") or position.get("open_quantity"))
    return status in {"OPEN", "ACTIVE", "MONITORING", "PARTIALLY_FILLED", "FILLED"} or qty > 0


def _direction_matches(direction: str, observed: str) -> bool:
    if direction == "BULLISH":
        return observed in {"BULLISH", "CALL", "LONG", "UP"}
    if direction == "BEARISH":
        return observed in {"BEARISH", "PUT", "SHORT", "DOWN"}
    return False


def build_trade_lifecycle(context: Optional[Mapping[str, Any]], prior: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    tc = normalize_trade_context(context)
    session = as_mapping(tc["session"]); session_state = as_mapping(session.get("session"))
    decision = as_mapping(tc["decision"]); authorization = as_mapping(decision.get("authorization"))
    committee = as_mapping(tc["decision_intelligence"])
    strategy = as_mapping(tc["strategy"]); contract_intel = as_mapping(tc["contract"])
    execution = as_mapping(tc["execution"]); mtf = as_mapping(tc["multi_timeframe"])
    flow = as_mapping(tc["institutional_flow"]); position = as_mapping(tc["position"])
    trade_health = as_mapping(tc["trade_health"])

    auth_state = _u(decision.get("authorization_state"))
    session_mode = _u(session_state.get("mode"))
    direction = _u(decision.get("dominant_direction") or committee.get("dominant_direction")) or "NEUTRAL"
    mtf_gate = _u(mtf.get("decision_gate")); mtf_bias = _u(mtf.get("dominant_direction") or mtf.get("higher_timeframe_bias"))
    flow_gate = _u(flow.get("decision_gate")); flow_bias = _u(flow.get("institutional_bias") or flow.get("dominant_direction"))
    execution_gate = _u(execution.get("decision_gate") or execution.get("gate"))
    strategy_gate = _u(strategy.get("decision_gate"))
    open_position = _position_open(position)

    entry = _f(position.get("entry_price") or position.get("average_price") or position.get("avg_price"))
    current = _f(position.get("current_price") or position.get("mark") or position.get("last_price"))
    quantity = _i(position.get("quantity") or position.get("contracts") or position.get("open_quantity"))
    initial_quantity = _i(position.get("initial_quantity") or position.get("original_quantity"), quantity)
    pnl_pct = _f(position.get("pnl_pct") or position.get("return_pct"))
    if not pnl_pct and entry > 0 and current > 0:
        pnl_pct = ((current - entry) / entry) * 100.0
    unrealized = _f(position.get("unrealized_pnl") or position.get("open_pnl"))
    minutes_held = _f(position.get("minutes_held") or position.get("hold_minutes"))

    target1 = _f(position.get("target_1") or position.get("tp1") or as_mapping(execution.get("targets")).get("target_1"))
    target2 = _f(position.get("target_2") or position.get("tp2") or as_mapping(execution.get("targets")).get("target_2"))
    target3 = _f(position.get("target_3") or position.get("tp3") or as_mapping(execution.get("targets")).get("target_3"))
    stop = _f(position.get("stop_price") or position.get("stop") or as_mapping(execution.get("risk_plan")).get("stop_price"))
    breakeven = entry if entry > 0 else None

    hard_blockers = []
    if session_mode == "STOP_TRADING": hard_blockers.append("Session Intelligence requires STOP_TRADING.")
    if auth_state == "DECISION_BLOCKED": hard_blockers.append("Phase 20 decision authority is blocked.")
    if _u(strategy.get("decision_gate")) == "STAND_DOWN": hard_blockers.append("Strategy Orchestration requires STAND_DOWN.")
    if mtf_gate == "STAND_DOWN" or flow_gate == "STAND_DOWN": hard_blockers.append("An upstream intelligence engine requires STAND_DOWN.")

    thesis_support = []
    thesis_conflicts = []
    if mtf_gate == "ALIGNED" and (_direction_matches(direction, mtf_bias) or mtf_bias in {"", "NEUTRAL"}):
        thesis_support.append("Multi-timeframe structure supports the original direction.")
    elif mtf_gate in {"TIMEFRAME_CONFLICT", "WAIT_FOR_ALIGNMENT"} or (mtf_bias and not _direction_matches(direction, mtf_bias)):
        thesis_conflicts.append("Multi-timeframe structure no longer cleanly supports the original direction.")
    if flow_gate == "INSTITUTIONAL_CONFIRMATION" and (_direction_matches(direction, flow_bias) or flow_bias in {"", "NEUTRAL"}):
        thesis_support.append("Institutional flow remains confirmatory.")
    elif flow_gate in {"FLOW_CONFLICT", "MIXED_FLOW"} or (flow_bias and not _direction_matches(direction, flow_bias)):
        thesis_conflicts.append("Institutional flow is mixed or conflicts with the original thesis.")

    health_score = _f(trade_health.get("score") or trade_health.get("trade_health_score") or position.get("trade_health_score"), 50.0)
    momentum_state = _u(position.get("momentum_state") or position.get("momentum") or trade_health.get("momentum_state"))
    structure_state = _u(position.get("structure_state") or trade_health.get("structure_state"))
    stop_hit = bool(position.get("stop_hit")) or (stop > 0 and current > 0 and ((direction == "BULLISH" and current <= stop) or (direction == "BEARISH" and current >= stop)))
    tp1_hit = bool(position.get("tp1_hit")) or (target1 > 0 and current > 0 and ((direction == "BULLISH" and current >= target1) or (direction == "BEARISH" and current <= target1)))
    tp2_hit = bool(position.get("tp2_hit")) or (target2 > 0 and current > 0 and ((direction == "BULLISH" and current >= target2) or (direction == "BEARISH" and current <= target2)))
    tp3_hit = bool(position.get("tp3_hit")) or (target3 > 0 and current > 0 and ((direction == "BULLISH" and current >= target3) or (direction == "BEARISH" and current <= target3)))

    lifecycle_state = "DECISION_AUTHORIZED"
    action = "WAIT_FOR_ENTRY"
    urgency = "NORMAL"
    reduce_pct = 0
    new_stop = stop or None
    reason = "Authorized decision is waiting for a confirmed position."

    if hard_blockers and open_position:
        lifecycle_state, action, urgency = "EXIT", "EXIT_POSITION", "IMMEDIATE"
        reduce_pct, reason = 100, hard_blockers[0]
    elif hard_blockers:
        lifecycle_state, action, urgency = "DECISION_BLOCKED", "STAND_DOWN", "IMMEDIATE"
        reason = hard_blockers[0]
    elif not open_position:
        if auth_state == "AUTHORIZED_FOR_PREVIEW":
            lifecycle_state, action = "ENTRY_PENDING", "PROCEED_TO_PHASE10_PREVIEW"
            reason = "Phase 20 authorized preview; Phase 10 exact confirmation remains mandatory."
        elif auth_state == "CONDITIONALLY_AUTHORIZED":
            lifecycle_state, action = "ENTRY_PENDING", "WAIT_FOR_FINAL_CONFIRMATION"
            reason = "The decision is conditionally authorized but secondary confirmation remains incomplete."
        else:
            lifecycle_state, action = "DECISION_AUTHORIZED", "WAIT_FOR_ENTRY"
            reason = "No active position exists and Phase 20 has not authorized preview."
    elif stop_hit:
        lifecycle_state, action, urgency = "EXIT", "EXIT_POSITION", "IMMEDIATE"
        reduce_pct, reason = 100, "The governed stop or invalidation level has failed."
    elif tp3_hit:
        lifecycle_state, action, urgency = "EXIT", "EXIT_POSITION", "HIGH"
        reduce_pct, reason = 100, "Final target reached; complete the planned exit."
    elif len(thesis_conflicts) >= 2 or health_score < 30 or momentum_state in {"FAILED", "REVERSING", "OPPOSING_ACCELERATION"}:
        lifecycle_state, action, urgency = "PROTECT", "REDUCE_AND_TIGHTEN", "HIGH"
        reduce_pct = 50 if quantity > 1 else 100
        new_stop = breakeven if breakeven is not None and pnl_pct > 0 else stop or current
        reason = thesis_conflicts[0] if thesis_conflicts else "Trade quality has deteriorated materially."
    elif tp2_hit:
        lifecycle_state, action = "RUNNER", "SCALE_AND_TRAIL"
        reduce_pct = 30 if quantity >= 3 else (50 if quantity >= 2 else 0)
        new_stop = max(entry, target1) if direction == "BULLISH" and entry > 0 else (min(entry, target1) if direction == "BEARISH" and entry > 0 and target1 > 0 else breakeven)
        reason = "Second target reached; realize additional profit and manage only the runner."
    elif tp1_hit or pnl_pct >= 20:
        lifecycle_state, action = "SCALE", "TAKE_PARTIAL_AND_PROTECT"
        reduce_pct = 40 if quantity >= 3 else (50 if quantity >= 2 else 0)
        new_stop = breakeven
        reason = "First profit objective reached; reduce exposure and move protection to breakeven."
    elif thesis_conflicts or health_score < 50 or momentum_state in {"WEAKENING", "STALLING"}:
        lifecycle_state, action = "PROTECT", "TIGHTEN_RISK"
        new_stop = breakeven if pnl_pct > 0 and breakeven is not None else stop
        reason = thesis_conflicts[0] if thesis_conflicts else "Momentum or trade health is weakening."
    else:
        lifecycle_state, action = "POSITION_ACTIVE", "HOLD_POSITION"
        reason = "The original thesis remains intact across the coordinated evidence stack."

    # Defensive recommendations change immediately; less-defensive changes require a stable repeat.
    prior_map = as_mapping(prior)
    prior_action = _u(prior_map.get("management_action"))
    defensive = action in {"EXIT_POSITION", "REDUCE_AND_TIGHTEN", "TIGHTEN_RISK", "STAND_DOWN"}
    stability = "STABLE"
    if prior_action and prior_action != action:
        stability = "DEFENSIVE_CHANGE_IMMEDIATE" if defensive else "PROMOTION_CONFIRMATION_REQUIRED"
        if not defensive and _u(prior_map.get("candidate_action")) != action:
            action = prior_action
            lifecycle_state = _u(prior_map.get("lifecycle_state")) or lifecycle_state
            stability = "HOLDING_PRIOR_ACTION_PENDING_REPEAT"

    contract = as_mapping(contract_intel.get("best_contract") or contract_intel.get("selected_contract"))
    lifecycle_id = _stable_id({
        "decision": decision.get("decision_id") or "NONE",
        "position": position.get("position_id") or position.get("symbol") or contract.get("symbol") or "NONE",
        "state": lifecycle_state,
        "action": action,
        "qty": quantity,
    })

    management_plan = {
        "action": action,
        "urgency": urgency,
        "reduce_position_pct": reduce_pct,
        "remaining_quantity_estimate": max(0, quantity - round(quantity * reduce_pct / 100.0)),
        "recommended_stop": new_stop,
        "breakeven_price": breakeven,
        "targets": {"tp1": target1 or None, "tp2": target2 or None, "tp3": target3 or None},
        "broker_called": False,
        "order_submitted": False,
        "requires_phase10_exact_confirmation": action in {"PROCEED_TO_PHASE10_PREVIEW"},
        "manual_execution_required": action not in {"HOLD_POSITION", "WAIT_FOR_ENTRY", "WAIT_FOR_FINAL_CONFIRMATION"},
    }

    provenance = [
        {"engine": "PHASE_20", "value": auth_state or "UNKNOWN", "role": "decision_authority"},
        {"engine": "PHASE_17", "value": mtf_gate or "UNKNOWN", "role": "structure_confirmation"},
        {"engine": "PHASE_18", "value": flow_gate or "UNKNOWN", "role": "institutional_confirmation"},
        {"engine": "PHASE_16", "value": execution_gate or "UNKNOWN", "role": "execution_context"},
        {"engine": "PHASE_14", "value": strategy_gate or "UNKNOWN", "role": "strategy_context"},
    ]

    return {
        "version": "PHASE_21",
        "as_of": utc_now_iso(),
        "mode": "INTEGRATED_TRADE_LIFECYCLE",
        "lifecycle_id": lifecycle_id,
        "lifecycle_state": lifecycle_state,
        "management_action": action,
        "candidate_action": action,
        "direction": direction,
        "position_open": open_position,
        "position_snapshot": {
            "quantity": quantity, "initial_quantity": initial_quantity, "entry_price": entry or None,
            "current_price": current or None, "unrealized_pnl": unrealized, "pnl_pct": round(pnl_pct, 2),
            "minutes_held": minutes_held, "trade_health_score": round(health_score, 1),
            "momentum_state": momentum_state or None, "structure_state": structure_state or None,
        },
        "management_plan": management_plan,
        "thesis": {
            "support": thesis_support,
            "conflicts": thesis_conflicts,
            "intact": not thesis_conflicts and not hard_blockers,
        },
        "hard_blockers": hard_blockers,
        "reason": reason,
        "stability": {"state": stability, "prior_action": prior_action or None, "defensive_changes": "IMMEDIATE", "promotions": "REQUIRE_STABLE_REPEAT"},
        "provenance": provenance,
        "shared_context": {"symbol": tc["symbol"], "decision_id": decision.get("decision_id"), "contract_symbol": contract.get("symbol"), "strategy": strategy.get("selected_strategy") or strategy.get("strategy")},
        "accountability": {"persist_recommendation": True, "capture_inputs": True, "capture_outcome": True, "autonomous_execution": False},
        "safety_note": "Advisory lifecycle management only. Phase 21 coordinates existing engines but cannot contact a broker, submit or modify orders, widen risk beyond the governed plan, bypass Phase 9 risk controls, bypass Phase 10 exact confirmation, or override upstream STOP_TRADING/STAND_DOWN authority.",
    }
