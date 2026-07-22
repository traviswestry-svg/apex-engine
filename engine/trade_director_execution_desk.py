"""APEX Trade Director Phase 16 — Institutional Execution Desk.

Deterministic, broker-neutral execution planning and quality analysis. The desk
uses Phase 15 contract intelligence plus caller-supplied quotes/order updates.
It never contacts a broker, submits an order, or bypasses Phase 9/10 controls.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from typing import Any, Dict, Mapping, Optional


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    return str(value or "").strip()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _nested(root: Mapping[str, Any], path: str, default: Any = None) -> Any:
    current: Any = root
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return default if current is None else current


def _round_tick(price: float, tick: float = 0.05) -> float:
    if price <= 0:
        return 0.0
    return round(round(price / tick) * tick, 2)


def _plan_id(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return "TD16-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()


def _selected_contract(context: Mapping[str, Any]) -> Dict[str, Any]:
    options = dict(context.get("options_intelligence") or {})
    contract = dict(options.get("best_contract") or {})
    if not contract:
        contract = dict(_nested(context, "phase15_last_intelligence.best_contract", {}) or {})
    return contract


def _quantity(context: Mapping[str, Any]) -> int:
    candidates = (
        _nested(context, "session_intelligence.dynamic_position_sizing.recommended_contracts", 0),
        _nested(context, "execution_readiness.action_quantity", 0),
        _nested(context, "position.quantity", 0),
        context.get("quantity"),
    )
    for value in candidates:
        number = _i(value, 0)
        if number > 0:
            return number
    return 1


def build_execution_plan(context: Optional[Dict[str, Any]], quote: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Build a confirmation-gated limit-price plan from cached/supplied data."""
    context = dict(context or {})
    quote = dict(quote or {})
    options = dict(context.get("options_intelligence") or {})
    phase15_gate = _text(options.get("decision_gate") or "CHAIN_REQUIRED").upper()
    strategy_gate = _text(_nested(context, "strategy_orchestration.decision_gate", "STAND_DOWN")).upper()
    contract = _selected_contract(context)

    bid = _f(quote.get("bid"), _f(contract.get("bid"), 0.0))
    ask = _f(quote.get("ask"), _f(contract.get("ask"), 0.0))
    last = _f(quote.get("last"), _f(contract.get("mid"), 0.0))
    if bid > 0 and ask >= bid:
        mid = (bid + ask) / 2.0
        spread = ask - bid
        spread_pct = spread / mid * 100.0 if mid else 0.0
    else:
        mid = last
        spread = 0.0
        spread_pct = 999.0

    side = _text(quote.get("side") or "BUY_TO_OPEN").upper()
    is_buy = side in {"BUY", "BUY_TO_OPEN", "BUY_OPEN", "BTO"}
    liquidity_score = _f(contract.get("score"), 0.0)
    urgency = "PATIENT"
    strategy_score = _f(_nested(context, "strategy_orchestration.selected_strategy.score", 0), 0)
    trade_health = _f(context.get("trade_health"), 0)
    if strategy_score >= 82 and trade_health >= 75:
        urgency = "ASSERTIVE"
    elif strategy_score >= 68:
        urgency = "BALANCED"

    if bid > 0 and ask >= bid:
        if is_buy:
            patient = mid
            balanced = mid + spread * 0.25
            assertive = ask - spread * 0.10
        else:
            patient = mid
            balanced = mid - spread * 0.25
            assertive = bid + spread * 0.10
        prices = {
            "PATIENT": _round_tick(patient),
            "BALANCED": _round_tick(balanced),
            "ASSERTIVE": _round_tick(assertive),
        }
    else:
        prices = {"PATIENT": 0.0, "BALANCED": 0.0, "ASSERTIVE": 0.0}

    limit_price = prices.get(urgency, prices["PATIENT"])
    max_slippage = max(0.05, min(0.40, spread * 0.50 if spread else 0.05))
    max_acceptable = _round_tick(limit_price + max_slippage if is_buy else max(0.01, limit_price - max_slippage))
    quantity = _quantity(context)

    blockers = []
    if strategy_gate == "STAND_DOWN":
        blockers.append("Phase 14 selected STAND_DOWN")
    if phase15_gate != "CONTRACT_CANDIDATE_SELECTED":
        blockers.append("Phase 15 has not selected a verified contract candidate")
    if not contract.get("symbol"):
        blockers.append("Contract identity is unavailable")
    if bid <= 0 or ask < bid:
        blockers.append("Valid two-sided quote is required")
    if spread_pct > 18:
        blockers.append("Bid/ask spread exceeds the Phase 15 hard limit")
    if quantity < 1:
        blockers.append("Order quantity is invalid")

    gate = "BLOCKED" if blockers else "READY_FOR_PHASE10_PREVIEW"
    payload = {
        "symbol": contract.get("symbol"), "side": side, "quantity": quantity,
        "limit_price": limit_price, "max_acceptable_price": max_acceptable,
        "phase15_gate": phase15_gate, "strategy_gate": strategy_gate,
    }
    return {
        "version": "PHASE_16", "as_of": _now(), "mode": "ADVISORY_EXECUTION_DESK",
        "decision_gate": gate, "plan_id": _plan_id(payload),
        "contract": {k: contract.get(k) for k in ("symbol", "expiration", "strike", "side", "delta", "bid", "ask", "mid", "score")},
        "order_plan": {
            "action": side, "quantity": quantity, "order_type": "LIMIT",
            "time_in_force": "DAY", "urgency": urgency,
            "limit_price": limit_price or None, "patient_price": prices["PATIENT"] or None,
            "balanced_price": prices["BALANCED"] or None, "assertive_price": prices["ASSERTIVE"] or None,
            "max_acceptable_price": max_acceptable or None,
            "estimated_notional": round(limit_price * quantity * 100, 2) if limit_price else None,
        },
        "market_quality": {
            "bid": bid or None, "ask": ask or None, "mid": round(mid, 3) if mid else None,
            "spread": round(spread, 3) if spread else None,
            "spread_pct": round(spread_pct, 2) if spread_pct < 999 else None,
            "contract_quality_score": liquidity_score,
            "quality": "HIGH" if spread_pct <= 5 else "ACCEPTABLE" if spread_pct <= 10 else "POOR",
        },
        "slippage_guard": {
            "maximum_slippage": round(max_slippage, 2),
            "cancel_replace_policy": "ONE_STEP_TOWARD_MARKET_THEN_REASSESS",
            "market_order_allowed": False,
            "chase_prohibited": True,
        },
        "blockers": blockers,
        "execution_authority": {
            "broker_called": False, "order_submitted": False,
            "phase9_bypassed": False, "phase10_confirmation_required": True,
            "live_execution_enabled": False,
        },
        "safety_note": "Phase 16 creates a broker-neutral execution plan only. Phase 9 risk approval and Phase 10 exact confirmation remain mandatory.",
    }


def assess_order_update(plan: Mapping[str, Any], update: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Assess partial fills, slippage, and order quality from a supplied update."""
    plan = dict(plan or {})
    update = dict(update or {})
    order_plan = dict(plan.get("order_plan") or {})
    intended_qty = max(0, _i(order_plan.get("quantity"), 0))
    filled_qty = max(0, min(intended_qty, _i(update.get("filled_quantity"), 0)))
    remaining = max(0, intended_qty - filled_qty)
    avg_fill = _f(update.get("average_fill_price"), 0.0)
    reference = _f(order_plan.get("limit_price"), 0.0)
    action = _text(order_plan.get("action")).upper()
    is_buy = action.startswith("BUY")
    slippage = (avg_fill - reference) if is_buy else (reference - avg_fill)
    slippage = slippage if avg_fill and reference else 0.0
    slippage_dollars = slippage * filled_qty * 100
    max_slippage = _f(_nested(plan, "slippage_guard.maximum_slippage", 0.05), 0.05)

    status = _text(update.get("status") or "WORKING").upper()
    if filled_qty >= intended_qty > 0:
        lifecycle = "FILLED"
    elif filled_qty > 0:
        lifecycle = "PARTIALLY_FILLED"
    elif status in {"CANCELLED", "REJECTED", "EXPIRED"}:
        lifecycle = status
    else:
        lifecycle = "WORKING"

    if lifecycle == "PARTIALLY_FILLED":
        next_action = "HOLD_REMAINDER" if slippage <= max_slippage else "CANCEL_REMAINDER"
    elif lifecycle == "WORKING":
        next_action = "MAINTAIN_LIMIT" if _i(update.get("age_seconds"), 0) < 20 else "REASSESS_ONE_TICK"
    else:
        next_action = "NONE"

    fill_ratio = (filled_qty / intended_qty) if intended_qty else 0.0
    quality = 100.0
    quality -= min(45.0, max(0.0, slippage) / max(0.01, max_slippage) * 35.0)
    quality -= 12.0 if lifecycle == "PARTIALLY_FILLED" else 0.0
    quality -= 20.0 if lifecycle in {"REJECTED", "CANCELLED", "EXPIRED"} else 0.0
    quality = max(0.0, min(100.0, quality))

    return {
        "version": "PHASE_16", "as_of": _now(), "plan_id": plan.get("plan_id"),
        "lifecycle_state": lifecycle, "intended_quantity": intended_qty,
        "filled_quantity": filled_qty, "remaining_quantity": remaining,
        "fill_ratio": round(fill_ratio, 3), "average_fill_price": avg_fill or None,
        "reference_limit_price": reference or None, "slippage_per_contract": round(slippage, 3),
        "estimated_slippage_dollars": round(slippage_dollars, 2),
        "execution_quality_score": round(quality, 1), "next_action": next_action,
        "requires_user_confirmation": next_action in {"CANCEL_REMAINDER", "REASSESS_ONE_TICK"},
        "broker_called": False,
    }
