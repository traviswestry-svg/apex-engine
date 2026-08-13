"""APEX Trade Director Phase 9 — Execution Readiness & Risk Guardrails.

Builds an advisory, confirmation-ready action preview from the Phase 8 policy.
This module performs no I/O, starts no workers, requests no market data, and
never sends, modifies, or cancels a broker order.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_ACTIONS = {"HOLD", "PROTECT_PROFIT", "MOVE_STOP_BE", "TRIM_25", "TRIM_50", "TRIM_75", "EXIT"}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _action(value: Any) -> str:
    action = str(value or "HOLD").upper().strip()
    aliases = {"EXIT_OR_REDUCE": "EXIT", "TAKE_PARTIAL": "TRIM_50"}
    action = aliases.get(action, action)
    return action if action in _ACTIONS else "HOLD"


def _contracts_for(action: str, held: int) -> int:
    if held <= 0 or action in {"HOLD", "PROTECT_PROFIT", "MOVE_STOP_BE"}:
        return 0
    if action == "EXIT":
        return held
    pct = {"TRIM_25": 0.25, "TRIM_50": 0.50, "TRIM_75": 0.75}.get(action, 0.0)
    # A protective trim must close at least one contract when a position exists.
    return min(held, max(1, int(round(held * pct)))) if pct else 0


def _token(payload: Dict[str, Any]) -> str:
    stable = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:20]


def build_execution_readiness(
    position: Dict[str, Any],
    management_policy: Optional[Dict[str, Any]],
    health_engine: Optional[Dict[str, Any]],
    position_intelligence: Optional[Dict[str, Any]],
    limits: Optional[Dict[str, Any]] = None,
    session: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a broker-neutral preview and deterministic risk gate."""
    position = dict(position or {})
    policy = dict(management_policy or {})
    health = dict(health_engine or {})
    intel = dict(position_intelligence or {})
    limits = dict(limits or {})
    session = dict(session or {})

    action = _action(policy.get("policy_action") or "HOLD")
    held = max(0, _i(position.get("held_qty") or position.get("quantity"), 0))
    close_qty = _contracts_for(action, held)
    remaining_qty = max(0, held - close_qty)
    premium = _f(position.get("option_current_price") or position.get("current_option_price") or position.get("option_entry_price"), 0.0)
    entry_premium = _f(position.get("option_entry_price"), premium)
    multiplier = max(1, _i(position.get("multiplier"), 100))
    current_exposure = round(max(0.0, premium) * multiplier * held, 2)
    remaining_exposure = round(max(0.0, premium) * multiplier * remaining_qty, 2)
    max_loss_estimate = round(max(0.0, entry_premium) * multiplier * remaining_qty, 2)

    max_contracts = max(1, _i(limits.get("max_contracts"), 3))
    max_trade_risk = max(0.0, _f(limits.get("max_trade_risk"), 2000.0))
    max_daily_loss = max(0.0, _f(limits.get("max_daily_loss"), 1000.0))
    max_daily_trades = max(1, _i(limits.get("max_daily_trades"), 3))
    daily_realized = _f(session.get("daily_realized_pnl"), 0.0)
    trades_today = max(0, _i(session.get("trades_today"), 0))

    checks = []
    def add(name: str, passed: Optional[bool], detail: str, severity: str = "BLOCK") -> None:
        checks.append({"name": name, "passed": passed, "detail": detail, "severity": severity})

    add("Position recognized", held > 0, f"{held} contract(s) currently recorded.")
    add("Contract limit", held <= max_contracts, f"Held {held}; configured maximum {max_contracts}.")
    if entry_premium > 0:
        add("Remaining capital at risk", max_loss_estimate <= max_trade_risk,
            f"Estimated remaining long-option maximum loss ${max_loss_estimate:,.0f}; limit ${max_trade_risk:,.0f}.")
    else:
        add("Remaining capital at risk", None, "Option premium is missing; maximum-loss estimate is unavailable.", "WARN")
    add("Daily loss lockout", daily_realized > -max_daily_loss,
        f"Recorded daily realized P/L ${daily_realized:,.0f}; lockout at -${max_daily_loss:,.0f}.")
    add("Daily trade limit", trades_today <= max_daily_trades,
        f"Recorded trades today {trades_today}; configured maximum {max_daily_trades}.")
    add("Policy confirmation", bool(policy), "Phase 8 policy is available." if policy else "Phase 8 policy is unavailable.")
    add("Action quantity", close_qty <= held, f"Preview closes {close_qty} and leaves {remaining_qty} contract(s).")

    blockers = [c for c in checks if c["passed"] is False and c["severity"] == "BLOCK"]
    warnings = [c for c in checks if c["passed"] is None or (c["passed"] is False and c["severity"] == "WARN")]
    requires_order = action in {"TRIM_25", "TRIM_50", "TRIM_75", "EXIT"}
    stop_only = action in {"PROTECT_PROFIT", "MOVE_STOP_BE"}

    if blockers:
        gate = "BLOCKED"
    elif action == "HOLD":
        gate = "MONITOR_ONLY"
    elif requires_order or stop_only:
        gate = "READY_FOR_USER_CONFIRMATION"
    else:
        gate = "REVIEW_REQUIRED"

    order_intent = {
        "intent_type": "CLOSE_POSITION" if action == "EXIT" else "REDUCE_POSITION" if requires_order else "MODIFY_PROTECTION" if stop_only else "NO_ACTION",
        "action": action,
        "symbol": position.get("option_symbol") or position.get("symbol") or position.get("ticker"),
        "underlying": position.get("ticker") or position.get("symbol"),
        "side": position.get("side"),
        "quantity": close_qty,
        "held_quantity": held,
        "remaining_quantity": remaining_qty,
        "order_type": "MARKETABLE_LIMIT_PREVIEW" if requires_order else "STOP_UPDATE_PREVIEW" if stop_only else "NONE",
        "limit_price": round(premium, 2) if premium > 0 and requires_order else None,
        "time_in_force": "DAY" if requires_order else None,
    }
    token_source = {
        "trade_id": position.get("trade_id"), "action": action, "quantity": close_qty,
        "premium": round(premium, 2), "held": held, "policy_version": policy.get("version"),
    }
    preview_id = _token(token_source)

    reversal = _f((intel.get("exit_probability") or {}).get("reversal_probability"), 0.0)
    health_score = _f(health.get("score"), 0.0)
    urgency = "CRITICAL" if action == "EXIT" and (health_score < 42 or reversal >= 72) else "HIGH" if action in {"EXIT", "TRIM_75", "TRIM_50"} else "NORMAL"

    return {
        "version": "PHASE_9",
        "preview_id": preview_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "gate": gate,
        "urgency": urgency,
        "policy_action": action,
        "order_intent": order_intent,
        "risk": {
            "current_exposure": current_exposure,
            "remaining_exposure": remaining_exposure,
            "estimated_remaining_max_loss": max_loss_estimate if entry_premium > 0 else None,
            "daily_realized_pnl": round(daily_realized, 2),
            "trades_today": trades_today,
        },
        "limits": {
            "max_contracts": max_contracts,
            "max_trade_risk": max_trade_risk,
            "max_daily_loss": max_daily_loss,
            "max_daily_trades": max_daily_trades,
        },
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "requires_explicit_confirmation": gate == "READY_FOR_USER_CONFIRMATION",
        "broker_handoff_ready": gate == "READY_FOR_USER_CONFIRMATION" and not blockers,
        "execution_enabled": False,
        "broker_adapter_status": "DISABLED",
        "safety_note": "Phase 9 creates a broker-neutral preview and risk gate only. It never transmits an order.",
    }
