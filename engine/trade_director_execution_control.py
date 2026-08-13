"""APEX Trade Director Phase 10 — Broker Execution Control Layer.

Sandbox-first, explicit-confirmation bridge from a Phase 9 readiness preview to the
existing E*TRADE adapter. This module is intentionally side-effect free: broker I/O
is performed only by the Flask routes after a user action.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from engine.execution.broker_interface import OrderIntent

_TERMINAL = {"FILLED", "REJECTED", "CANCELED", "EXPIRED"}
_VALID_STATES = {
    "CREATED", "AWAITING_CONFIRMATION", "SUBMITTING", "ACCEPTED",
    "PARTIALLY_FILLED", "FILLED", "REJECTED", "CANCELED", "EXPIRED",
    "UNKNOWN", "RECONCILIATION_REQUIRED",
}


def _envb(name: str, default: bool = False) -> bool:
    return os.getenv(name, "true" if default else "false").strip().lower() in {"1", "true", "yes", "on"}


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


def _token(payload: Dict[str, Any]) -> str:
    stable = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]


def execution_mode() -> str:
    requested = os.getenv("APEX_TD10_MODE", "DISABLED").strip().upper()
    if requested not in {"DISABLED", "SANDBOX", "PAPER", "LIVE_CONFIRMATION"}:
        requested = "DISABLED"
    return requested


def build_control_status(
    readiness: Optional[Dict[str, Any]],
    last_decision: Optional[Dict[str, Any]],
    session: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    readiness = dict(readiness or {})
    last_decision = dict(last_decision or {})
    session = dict(session or {})
    mode = execution_mode()
    preview_id = str(readiness.get("preview_id") or "")
    acknowledged = (
        str(last_decision.get("decision") or "") == "ACKNOWLEDGE_PREVIEW"
        and str(last_decision.get("preview_id") or "") == preview_id
    )
    intent = dict(readiness.get("order_intent") or {})
    blockers = list(readiness.get("blockers") or [])
    pending = dict(session.get("active_order") or {})
    pending_state = str(pending.get("state") or "")
    pending_open = bool(pending and pending_state not in _TERMINAL)

    checks = [
        {"name": "Phase 9 gate", "passed": readiness.get("gate") == "READY_FOR_USER_CONFIRMATION", "detail": str(readiness.get("gate") or "NO_PREVIEW")},
        {"name": "Phase 9 acknowledgement", "passed": acknowledged, "detail": "Current preview acknowledged." if acknowledged else "Acknowledge the current Phase 9 preview first."},
        {"name": "Orderable intent", "passed": _i(intent.get("quantity"), 0) > 0 and bool(intent.get("symbol")), "detail": f"{_i(intent.get('quantity'), 0)} contract(s) · {intent.get('symbol') or 'missing contract'}"},
        {"name": "Risk blockers", "passed": not blockers, "detail": "No Phase 9 blockers." if not blockers else f"{len(blockers)} blocking risk check(s)."},
        {"name": "Execution mode", "passed": mode != "DISABLED", "detail": mode},
        {"name": "Single-flight control", "passed": not pending_open, "detail": "No unresolved broker order." if not pending_open else f"Existing order state: {pending_state}."},
    ]
    blocked = [c for c in checks if not c["passed"]]
    gate = "READY_TO_PREVIEW" if not blocked else "BLOCKED"
    if mode == "PAPER" and not blocked:
        gate = "READY_FOR_PAPER_PREVIEW"
    return {
        "version": "PHASE_10",
        "mode": mode,
        "gate": gate,
        "phase9_preview_id": preview_id,
        "acknowledged": acknowledged,
        "checks": checks,
        "blockers": blocked,
        "active_order": pending or None,
        "supported_actions": ["TRIM_25", "TRIM_50", "TRIM_75", "EXIT"],
        "live_execution_allowed": mode == "LIVE_CONFIRMATION" and _envb("APEX_TD10_ALLOW_LIVE", False),
        "confirmation_required": True,
        "safety_note": "Phase 10 is fail-closed. Broker placement requires an exact, current preview and explicit user confirmation.",
    }


def order_intent_from_readiness(readiness: Dict[str, Any]) -> OrderIntent:
    intent = dict((readiness or {}).get("order_intent") or {})
    quantity = _i(intent.get("quantity"), 0)
    symbol = str(intent.get("underlying") or "SPX").strip().upper()
    osi_key = str(intent.get("symbol") or "").strip()
    side = str(intent.get("side") or "").strip().upper()
    limit_price = _f(intent.get("limit_price"), 0.0)
    if quantity <= 0:
        raise ValueError("Order quantity must be greater than zero")
    if not osi_key:
        raise ValueError("A verified option symbol/OSI key is required")
    if side not in {"CALL", "PUT"}:
        raise ValueError("Option side must be CALL or PUT")
    if limit_price <= 0:
        raise ValueError("A positive limit price is required")
    return OrderIntent(
        symbol=symbol,
        osi_key=osi_key,
        side=side,
        action="SELL_CLOSE",
        quantity=quantity,
        order_type="LIMIT",
        limit_price=round(limit_price, 2),
        time_in_force="DAY",
        price_type_note="APEX Trade Director Phase 10 confirmation-gated management order",
        tag=str(readiness.get("policy_action") or "MANAGE"),
    )


def create_order_record(readiness: Dict[str, Any], broker_preview: Dict[str, Any], mode: str) -> Dict[str, Any]:
    intent = order_intent_from_readiness(readiness)
    broker_data = dict(broker_preview or {})
    broker_preview_id = str(broker_data.get("preview_id") or "")
    seed = {
        "phase9_preview_id": readiness.get("preview_id"),
        "broker_preview_id": broker_preview_id,
        "intent": intent.to_dict(),
        "mode": mode,
    }
    now = datetime.now(timezone.utc).isoformat()
    return {
        "control_id": _token(seed),
        "state": "AWAITING_CONFIRMATION",
        "mode": mode,
        "created_at": now,
        "updated_at": now,
        "phase9_preview_id": readiness.get("preview_id"),
        "broker_preview_id": broker_preview_id,
        "intent": intent.to_dict(),
        "broker_preview": broker_data,
        "confirmation_token": _token({"control": _token(seed), "preview": broker_preview_id}),
        "submission": None,
        "reconciliation": None,
        "errors": [],
    }


def validate_confirmation(
    record: Dict[str, Any],
    readiness: Dict[str, Any],
    control_id: str,
    confirmation_token: str,
    confirmation_text: str,
) -> Tuple[bool, str]:
    if not record:
        return False, "No prepared broker order"
    if str(record.get("state")) != "AWAITING_CONFIRMATION":
        return False, f"Order is not awaiting confirmation ({record.get('state')})"
    if str(record.get("control_id")) != str(control_id):
        return False, "Control ID mismatch"
    if str(record.get("confirmation_token")) != str(confirmation_token):
        return False, "Confirmation token mismatch"
    if str(record.get("phase9_preview_id")) != str((readiness or {}).get("preview_id") or ""):
        return False, "Phase 9 preview is stale"
    if str(confirmation_text or "").strip().upper() != "CONFIRM ORDER":
        return False, 'Type "CONFIRM ORDER" exactly'
    return True, "validated"


def reconcile_position(record: Dict[str, Any], positions: Any) -> Dict[str, Any]:
    positions = list(positions or [])
    intent = dict(record.get("intent") or {})
    osi = str(intent.get("osi_key") or "")
    expected_reduction = _i(intent.get("quantity"), 0)
    before = _i(record.get("broker_quantity_before"), 0)
    match = next((p for p in positions if str(p.get("osi_key") or p.get("symbol") or "") == osi), None)
    after = _i((match or {}).get("quantity"), 0)
    expected_after = max(0, before - expected_reduction)
    matched = after == expected_after
    return {
        "status": "MATCHED" if matched else "RECONCILIATION_REQUIRED",
        "symbol": osi,
        "quantity_before": before,
        "expected_quantity_after": expected_after,
        "broker_quantity_after": after,
        "matched": matched,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
