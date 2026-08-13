"""engine/director/lifecycle.py — entry gating + active management (Parts 5,9,10,11).

Four cohesive pieces of the active-management brain:

  Part 5  scalp_vs_conviction()  — which entry type (if any) is approved
  Part 9  protect_profit()       — the trade works but conditions are weakening
  Part 10 scale_decision()       — SCALE_OUT_25/50/75 / HOLD_RUNNER (not on a bare
                                   target touch — considers flow/auction/walls/time)
  Part 11 exit_decision()        — EXIT hierarchy: flow reversal > level failure >
                                   thesis invalidation > target reached

Every function returns a small dict the Director composes; none of them place
orders or bypass execution controls.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .contracts import FlowAcceleration, HoldLevel


def _u(v: Any) -> str:
    return str(v or "").upper()


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


# ── Part 5 — scalp vs conviction ─────────────────────────────────────────────

def scalp_vs_conviction(
    *,
    side: str,
    conflict_alignment: str,
    permitted_type: str,
    flow_acc: FlowAcceleration,
    execution: Dict[str, Any],
    market_state: Dict[str, Any],
    hold_level: HoldLevel,
    pine_fresh: bool,
    risk_reward: Optional[float] = None,
) -> Dict[str, Any]:
    """Decide SCALP / CONVICTION / NONE and give the gating reasons."""
    side = _u(side)
    fc = _u(flow_acc.classification)
    exec_ready = _u(execution.get("stage")) in ("ARMED", "EXECUTE") or bool(execution.get("trigger_active"))
    aligned_flow = (side == "CALL" and fc in ("BUYERS_ACCELERATING", "BUYERS_STEADY", "BULLISH_FLOW_REVERSAL")) or \
                   (side == "PUT" and fc in ("SELLERS_ACCELERATING", "SELLERS_STEADY", "BEARISH_FLOW_REVERSAL"))
    strong_flow = (side == "CALL" and fc == "BUYERS_ACCELERATING") or \
                  (side == "PUT" and fc == "SELLERS_ACCELERATING")
    rr_ok = (risk_reward is None) or (risk_reward >= 1.2)

    reasons: List[str] = []
    if permitted_type == "NONE":
        return {"trade_type": "NONE", "approved": False,
                "reasons": ["Hard veto or no permitted entry type."]}

    # CONVICTION path
    if permitted_type == "CONVICTION" and conflict_alignment == "STRONG_ALIGNMENT" \
       and aligned_flow and pine_fresh and hold_level.available and rr_ok:
        reasons = ["Strong institutional alignment across engines.",
                   "Flow supports the side.",
                   "Fresh Pine trigger.",
                   "Clean dynamic hold level available."]
        return {"trade_type": "CONVICTION", "approved": True, "reasons": reasons}

    # SCALP path — short-term alignment even if slower engines don't all agree
    scalp_ok = strong_flow and (exec_ready or pine_fresh) and hold_level.available and rr_ok
    if scalp_ok and conflict_alignment != "VETO":
        reasons = ["Strong short-term flow acceleration.",
                   "Execution trigger / fresh Pine present.",
                   "Clear invalidation via dynamic hold level.",
                   "Acceptable reward/risk."]
        return {"trade_type": "SCALP", "approved": True, "reasons": reasons}

    # not yet — say what's missing
    if not strong_flow:
        reasons.append("Waiting for short-term flow acceleration to confirm.")
    if not (exec_ready or pine_fresh):
        reasons.append("No fresh execution trigger yet.")
    if not hold_level.available:
        reasons.append("No clean invalidation level near price.")
    if not rr_ok:
        reasons.append("Reward/risk not yet acceptable.")
    return {"trade_type": permitted_type, "approved": False, "reasons": reasons or ["Setup not ready."]}


# ── Part 9 — protect profit ──────────────────────────────────────────────────

def protect_profit(
    *,
    side: str,
    market_state: Dict[str, Any],
    flow_acc: FlowAcceleration,
    hold_level: HoldLevel,
    position: Dict[str, Any],
    time_in_trade_s: float,
    scalp_max_seconds: float = 420.0,
) -> Dict[str, Any]:
    """Return {trigger: bool, guidance: str, reasons: []} when the trade is
    working but conditions are weakening."""
    side = _u(side)
    ms = market_state or {}
    fc = _u(flow_acc.classification)
    price = _f(ms.get("price"))
    t1 = _f(position.get("target1"))
    reasons: List[str] = []
    bullish = side == "CALL"

    near_t1 = False
    if t1 and price:
        if bullish and price >= t1 - abs(t1) * 0.0006:
            near_t1 = True
        if not bullish and price <= t1 + abs(t1) * 0.0006:
            near_t1 = True
    if near_t1:
        reasons.append("Target 1 approached/reached.")

    weakening = (bullish and fc in ("BUYERS_WEAKENING", "FLOW_EXHAUSTION")) or \
                (not bullish and fc in ("SELLERS_WEAKENING", "FLOW_EXHAUSTION"))
    if weakening:
        reasons.append("Flow acceleration weakening.")

    opposing = (bullish and fc in ("SELLERS_STEADY", "SELLERS_WEAKENING", "SELLERS_ACCELERATING")) or \
               (not bullish and fc in ("BUYERS_STEADY", "BUYERS_WEAKENING", "BUYERS_ACCELERATING"))
    opp_accel = (bullish and fc == "SELLERS_ACCELERATING") or (not bullish and fc == "BUYERS_ACCELERATING")
    if opposing:
        reasons.append("Opposing flow accelerating." if opp_accel else "Opposing flow building.")

    # wall proximity against the side
    wall = _f(ms.get("call_wall")) if bullish else _f(ms.get("put_wall"))
    if wall and price:
        near_wall = abs(wall - price) <= max(2.0, abs(price) * 0.0008)
        if (bullish and price <= wall and near_wall) or (not bullish and price >= wall and near_wall):
            reasons.append(("Call" if bullish else "Put") + " wall approaching.")

    poc_stall = _u((ms).get("poc_migration")) == "STABLE"
    if poc_stall and near_t1:
        reasons.append("POC migration stalling near target.")

    overtime = time_in_trade_s > scalp_max_seconds
    if overtime:
        reasons.append("Time in trade exceeds expected scalp duration — theta decay material.")

    trigger = bool(reasons)
    if not trigger:
        return {"trigger": False, "guidance": "", "reasons": []}

    # guidance selection
    if near_t1 and (weakening or opposing):
        guidance = "SCALE_50"
    elif overtime or weakening:
        guidance = "TIGHTEN_HOLD_LEVEL"
    elif near_t1:
        guidance = "MOVE_STOP_TO_BREAKEVEN"
    else:
        guidance = "TIGHTEN_HOLD_LEVEL"
    return {"trigger": True, "guidance": guidance, "reasons": reasons}


# ── Part 10 — scale-out ──────────────────────────────────────────────────────

def scale_decision(
    *,
    side: str,
    market_state: Dict[str, Any],
    flow_acc: FlowAcceleration,
    position: Dict[str, Any],
    time_in_trade_s: float,
) -> Dict[str, Any]:
    """Return {action, reasons}. action ∈ SCALE_OUT_25/50/75/HOLD_RUNNER/NONE.

    Deliberately does NOT scale purely because a static target was touched — it
    weighs flow strength/acceleration, auction, walls, R achieved and time.
    """
    side = _u(side)
    ms = market_state or {}
    fc = _u(flow_acc.classification)
    price = _f(ms.get("price"))
    entry = _f(position.get("entry_price"))
    t1, t2, t3 = _f(position.get("target1")), _f(position.get("target2")), _f(position.get("target3"))
    bullish = side == "CALL"
    reasons: List[str] = []

    def reached(target: float) -> bool:
        if not target or not price:
            return False
        return price >= target if bullish else price <= target

    strong = (bullish and fc == "BUYERS_ACCELERATING") or (not bullish and fc == "SELLERS_ACCELERATING")
    fading = (bullish and fc in ("BUYERS_WEAKENING", "FLOW_EXHAUSTION")) or \
             (not bullish and fc in ("SELLERS_WEAKENING", "FLOW_EXHAUSTION"))
    reversing = (bullish and fc in ("SELLERS_ACCELERATING", "BEARISH_FLOW_REVERSAL")) or \
                (not bullish and fc in ("BUYERS_ACCELERATING", "BULLISH_FLOW_REVERSAL"))

    if reached(t3):
        reasons.append("Target 3 reached.")
        return {"action": "SCALE_OUT_75" if not reversing else "SCALE_OUT_75", "reasons": reasons}
    if reached(t2):
        reasons.append("Target 2 reached.")
        if strong:
            reasons.append("Flow still accelerating — keep a runner.")
            return {"action": "SCALE_OUT_50", "reasons": reasons}
        return {"action": "SCALE_OUT_75", "reasons": reasons}
    if reached(t1):
        reasons.append("Target 1 reached.")
        if strong:
            reasons.append("Buyer/seller flow still accelerating — hold the majority.")
            return {"action": "SCALE_OUT_25", "reasons": reasons}
        if fading or reversing:
            reasons.append("Flow decelerating near target — protect realized profit.")
            return {"action": "SCALE_OUT_50", "reasons": reasons}
        return {"action": "SCALE_OUT_50", "reasons": reasons}

    # no target hit — scale only if flow is exhausting with open profit
    if entry and price and fading:
        in_profit = (price > entry) if bullish else (price < entry)
        if in_profit:
            reasons.append("Flow exhausting while in profit before target — take partial.")
            return {"action": "SCALE_OUT_25", "reasons": reasons}

    if strong:
        return {"action": "HOLD_RUNNER", "reasons": ["Flow still accelerating — no scale."]}
    return {"action": "NONE", "reasons": []}


# ── Part 11 — exit hierarchy ─────────────────────────────────────────────────

def exit_decision(
    *,
    side: str,
    thesis_status: str,
    market_state: Dict[str, Any],
    flow_acc: FlowAcceleration,
    hold_level: HoldLevel,
    position: Dict[str, Any],
) -> Dict[str, Any]:
    """Return {exit: bool, kind, urgency, reasons}. kind in
    EXIT_FLOW_REVERSAL / EXIT_LEVEL_FAILURE / EXIT_THESIS_INVALIDATION /
    EXIT_TARGET / "".
    """
    side = _u(side)
    ms = market_state or {}
    fc = _u(flow_acc.classification)
    price = _f(ms.get("price"))
    bullish = side == "CALL"
    reasons: List[str] = []

    # 1) flow reversal (highest priority — momentum has flipped)
    reversal = (bullish and fc == "BEARISH_FLOW_REVERSAL") or (not bullish and fc == "BULLISH_FLOW_REVERSAL")
    opp_accel = (bullish and fc == "SELLERS_ACCELERATING") or (not bullish and fc == "BUYERS_ACCELERATING")
    level_lost = False
    if hold_level.available and hold_level.level and price:
        level_lost = (price < hold_level.level) if hold_level.direction == "ABOVE" else (price > hold_level.level)

    if reversal or (opp_accel and level_lost):
        reasons.append("Opposing flow has overtaken the position.")
        if level_lost:
            reasons.append(f"Dynamic hold level {hold_level.level} failed.")
        # Combined level-break + accelerating-opposite flow is an emergency exit;
        # a lone classifier reversal is urgent but passes the confirmation window.
        urgency = "CRITICAL" if (opp_accel and level_lost) else "URGENT"
        return {"exit": True, "kind": "EXIT_FLOW_REVERSAL", "urgency": urgency, "reasons": reasons}

    # 2) level failure (structure broke; confirm with any opposing pressure)
    if level_lost:
        opp_pressure = (bullish and fc in ("SELLERS_ACCELERATING", "SELLERS_STEADY")) or \
                       (not bullish and fc in ("BUYERS_ACCELERATING", "BUYERS_STEADY"))
        if opp_pressure:
            reasons.append(f"Price lost {hold_level.source} hold level ({hold_level.level}) with opposing flow.")
            return {"exit": True, "kind": "EXIT_LEVEL_FAILURE", "urgency": "URGENT", "reasons": reasons}
        reasons.append(f"Price below hold level {hold_level.level} — watch for confirmation.")

    # 3) thesis invalidation
    if thesis_status == "THESIS_INVALIDATED":
        reasons.append("Original thesis invalidated.")
        return {"exit": True, "kind": "EXIT_THESIS_INVALIDATION", "urgency": "URGENT", "reasons": reasons}

    # 4) target reached (fullest target)
    t2, t3 = _f(position.get("target2")), _f(position.get("target3"))
    final_t = t3 or t2
    if final_t and price and ((price >= final_t) if bullish else (price <= final_t)):
        reasons.append("Final target reached.")
        return {"exit": True, "kind": "EXIT_TARGET", "urgency": "NORMAL", "reasons": reasons}

    return {"exit": False, "kind": "", "urgency": "NORMAL", "reasons": reasons}
