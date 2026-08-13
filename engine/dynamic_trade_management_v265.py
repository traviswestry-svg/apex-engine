"""APEX 26.5 — Dynamic Trade Management Engine (advisory, deterministic).

Given an open position and current market state, it recommends management
actions: stop-loss placement, break-even shift, scale-out / scale-in, trailing
stop, profit lock, and time / volatility / structure based exits. It recommends
only — it does not modify, submit, or cancel any order. ``production_effect`` NONE.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional

VERSION = "26.5.0_DYNAMIC_TRADE_MANAGEMENT"
SCHEMA_VERSION = "apex.trade_management.v265.v1"

ACTIONS = ("HOLD", "MOVE_STOP", "BREAK_EVEN", "SCALE_OUT", "SCALE_IN",
           "TRAIL_STOP", "PROFIT_LOCK", "TIME_EXIT", "VOLATILITY_EXIT", "STRUCTURE_EXIT")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _round(v: Any, p: int = 4) -> Optional[float]:
    return None if v is None else round(float(v), p)


def manage(root: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    root = root if isinstance(root, Mapping) else {}
    pos = _mapping(root.get("position") or root.get("open_trade"))
    entry = _number(pos.get("entry_premium"))
    current = _number(pos.get("current_premium") or _mapping(root.get("quote")).get("mid"))
    stop = _number(pos.get("stop_premium"))
    target = _number(pos.get("target_premium"))
    contracts = int(_number(pos.get("contracts"), 0))
    held_seconds = _number(pos.get("held_seconds"))
    max_hold = _number(pos.get("max_hold_seconds"), 23400)

    if entry <= 0 or current <= 0 or contracts <= 0:
        return {"ok": True, "version": VERSION, "recommended_actions": [],
                "primary_action": "HOLD", "reason": "No open position or incomplete data.",
                "production_effect": "NONE"}

    pnl_pct = (current - entry) / entry * 100
    r_multiple = ((current - entry) / (entry - stop)) if (entry - stop) > 0 else None

    vix = _number(_mapping(root.get("volatility") or root.get("vol")).get("vix"), 16.0)
    structure_broken = bool(_mapping(root.get("market_state")).get("structure_broken"))
    thesis_intact = _mapping(root.get("market_state")).get("thesis_intact", True)

    actions: list[dict[str, Any]] = []

    def add(action: str, reason: str, detail: Optional[dict] = None):
        actions.append({"action": action, "reason": reason, **({"detail": detail} if detail else {})})

    # Profit-based management.
    if r_multiple is not None and r_multiple >= 1.0 and pnl_pct > 0:
        add("BREAK_EVEN", "Trade at ~1R; move stop to break-even to remove risk.",
            {"new_stop_premium": _round(entry)})
    if r_multiple is not None and r_multiple >= 1.5:
        add("SCALE_OUT", "At 1.5R+; take partial profit and let a runner work.",
            {"scale_fraction": 0.5})
        add("TRAIL_STOP", "Trail the stop below recent structure to protect gains.",
            {"trail_to_premium": _round(entry + (current - entry) * 0.5)})
    if target and current >= target:
        add("PROFIT_LOCK", "Primary target reached; lock profit or tighten aggressively.")

    # Loss / invalidation management.
    if current <= stop:
        add("STRUCTURE_EXIT" if structure_broken else "MOVE_STOP",
            "Price at/below stop; exit per plan." if not structure_broken
            else "Stop hit with broken structure; exit now.")
    if structure_broken and thesis_intact is False:
        add("STRUCTURE_EXIT", "Market structure broke against the thesis; exit.")

    # Time / volatility exits.
    if held_seconds >= max_hold * 0.9:
        add("TIME_EXIT", "Approaching max hold for a 0DTE position; exit into decay.")
    if vix >= 30 and pnl_pct > 0:
        add("VOLATILITY_EXIT", "Volatility spike; harvest gains before mean reversion.")

    # Add-on.
    if r_multiple is not None and 0 < r_multiple < 0.5 and thesis_intact and vix < 22:
        add("SCALE_IN", "Early, thesis intact, calm vol: optional add within risk limits.",
            {"note": "Only if total risk stays within max_risk_per_trade."})

    primary = actions[0]["action"] if actions else "HOLD"
    return {
        "ok": True,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "primary_action": primary,
        "recommended_actions": actions,
        "position_state": {
            "pnl_pct": _round(pnl_pct, 2),
            "r_multiple": _round(r_multiple, 2) if r_multiple is not None else None,
            "held_seconds": held_seconds,
        },
        "note": "Advisory only — no stop/target/order is modified or submitted by this engine.",
        "production_effect": "NONE",
    }


def status() -> dict[str, Any]:
    return {"status": "READY", "engine": "DYNAMIC_TRADE_MANAGEMENT", "version": VERSION,
            "actions": list(ACTIONS), "places_orders": False, "modifies_orders": False,
            "production_effect": "NONE"}
