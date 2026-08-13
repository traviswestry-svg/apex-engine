"""APEX Trade Director Phase 30 — Execution Certification & Production Readiness.

Safety-first certification, preview, confirmation, reconciliation, and kill-switch
controls. The module never submits a live order and exposes no broker mutation path.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from threading import RLock
from typing import Any, Dict, Mapping, Optional
from uuid import uuid4

VERSION = "PHASE_30"
_LOCK = RLock()
_STATE: Dict[str, Any] = {
    "kill_switch": {"active": False, "scope": "GLOBAL", "reason": "", "changed_at": None},
    "intents": {},
    "previews": {},
    "confirmations": {},
    "reconciliation": {"status": "PENDING", "checked_at": None, "mismatches": []},
    "metrics": {"preview_attempts": 0, "preview_successes": 0, "paper_trades": 0, "duplicate_orders": 0},
}


def _m(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(payload: Mapping[str, Any]) -> str:
    import json
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def reset_execution_certification_state() -> None:
    """Reset in-memory state for deterministic tests and local restarts."""
    with _LOCK:
        _STATE["kill_switch"] = {"active": False, "scope": "GLOBAL", "reason": "", "changed_at": None}
        _STATE["intents"] = {}
        _STATE["previews"] = {}
        _STATE["confirmations"] = {}
        _STATE["reconciliation"] = {"status": "PENDING", "checked_at": None, "mismatches": []}
        _STATE["metrics"] = {"preview_attempts": 0, "preview_successes": 0, "paper_trades": 0, "duplicate_orders": 0}


def _broker_health(context: Mapping[str, Any]) -> Dict[str, Any]:
    broker = _m(context.get("broker_health") or context.get("etrade_health"))
    sandbox = bool(broker.get("sandbox", context.get("broker_mode", "SANDBOX") != "LIVE"))
    checks = {
        "authentication": bool(broker.get("authenticated", False)),
        "token_fresh": bool(broker.get("token_fresh", False)),
        "account_access": bool(broker.get("account_access", False)),
        "quote_access": bool(broker.get("quote_access", False)),
        "option_chain_access": bool(broker.get("option_chain_access", False)),
        "preview_supported": bool(broker.get("preview_supported", False)),
        "order_status_supported": bool(broker.get("order_status_supported", False)),
        "cancel_replace_supported": bool(broker.get("cancel_replace_supported", False)),
        "position_access": bool(broker.get("position_access", False)),
        "balance_access": bool(broker.get("balance_access", False)),
    }
    passed = sum(checks.values())
    return {
        "broker": str(broker.get("broker") or "ETRADE").upper(),
        "environment": "SANDBOX" if sandbox else "LIVE_LOCKED",
        "status": "HEALTHY" if passed == len(checks) else "DEGRADED" if passed >= 5 else "UNAVAILABLE",
        "score": round(passed / len(checks) * 100.0, 1),
        "checks": checks,
        "live_submission_enabled": False,
    }


def build_order_intent(context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    ctx = dict(context or {})
    candidate = _m(ctx.get("order_intent") or ctx.get("candidate_order"))
    allocation = _m(ctx.get("portfolio_allocation"))
    alloc_candidate = _m(allocation.get("candidate_allocation"))
    options = _m(ctx.get("options_intelligence"))
    contract = _m(options.get("best_candidate") or options.get("selected_contract"))
    decision = _m(ctx.get("institutional_decision_engine"))
    authorization = _m(ctx.get("authorization") or decision.get("authorization"))
    qty = max(0, int(_f(candidate.get("quantity") or contract.get("quantity") or 1)))
    limit_price = max(0.0, _f(candidate.get("limit_price") or contract.get("mid") or contract.get("price")))
    intent = {
        "order_intent_id": str(candidate.get("order_intent_id") or uuid4()),
        "trade_id": str(candidate.get("trade_id") or ctx.get("trade_id") or uuid4()),
        "symbol": str(candidate.get("symbol") or ctx.get("symbol") or "SPX").upper(),
        "option_symbol": str(candidate.get("option_symbol") or contract.get("option_symbol") or contract.get("symbol") or ""),
        "side": str(candidate.get("side") or contract.get("side") or decision.get("direction") or "").upper(),
        "quantity": qty,
        "order_type": str(candidate.get("order_type") or "LIMIT").upper(),
        "limit_price": round(limit_price, 2),
        "time_in_force": str(candidate.get("time_in_force") or "DAY").upper(),
        "estimated_debit_or_credit": str(candidate.get("estimated_debit_or_credit") or "DEBIT").upper(),
        "maximum_loss": round(_f(candidate.get("maximum_loss") or alloc_candidate.get("recommended_risk_dollars")), 2),
        "portfolio_risk_after_fill": round(_f(candidate.get("portfolio_risk_after_fill") or _m(allocation.get("portfolio_summary")).get("total_risk_dollars")) + _f(candidate.get("maximum_loss") or alloc_candidate.get("recommended_risk_dollars")), 2),
        "authorization_id": str(candidate.get("authorization_id") or authorization.get("authorization_id") or ""),
        "allocation_id": str(candidate.get("allocation_id") or allocation.get("allocation_id") or ""),
        "lineage_id": str(candidate.get("lineage_id") or _m(ctx.get("data_lineage")).get("lineage_id") or ""),
        "confirmation_required": True,
        "created_at": _now(),
        "expires_at": str(candidate.get("expires_at") or (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()),
        "state": "DRAFT",
    }
    intent["intent_hash"] = _hash(intent)
    return intent


def validate_order_intent(intent: Mapping[str, Any], context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    ctx = dict(context or {})
    allocation = _m(ctx.get("portfolio_allocation"))
    broker = _broker_health(ctx)
    kill = deepcopy(_STATE["kill_switch"])
    required = ["order_intent_id", "trade_id", "symbol", "option_symbol", "side", "quantity", "order_type", "limit_price", "authorization_id"]
    gates = {
        "contract_complete": all(intent.get(k) not in (None, "", 0) for k in required),
        "market_session_valid": bool(ctx.get("market_session_valid", ctx.get("is_tradeable", False))),
        "data_fresh": bool(ctx.get("data_fresh", False)),
        "decision_authorized": bool(ctx.get("decision_authorized", bool(intent.get("authorization_id")))),
        "authorization_unexpired": bool(ctx.get("authorization_unexpired", True)),
        "portfolio_allocation_approved": allocation.get("allocation_state") in {"ALLOCATABLE", "CONSTRAINED"} or bool(ctx.get("portfolio_allocation_approved", False)),
        "daily_loss_limit_intact": not bool(ctx.get("daily_loss_limit_breached", False)),
        "position_limit_intact": not bool(ctx.get("position_limit_breached", False)),
        "liquidity_acceptable": bool(ctx.get("liquidity_acceptable", False)),
        "spread_width_acceptable": bool(ctx.get("spread_width_acceptable", False)),
        "buying_power_sufficient": bool(ctx.get("buying_power_sufficient", False)),
        "broker_connection_healthy": broker["status"] == "HEALTHY",
        "kill_switch_inactive": not kill.get("active", False),
        "live_execution_locked": True,
    }
    with _LOCK:
        duplicate = any(v.get("intent_hash") == intent.get("intent_hash") for v in _STATE["intents"].values())
        if duplicate:
            _STATE["metrics"]["duplicate_orders"] += 1
    gates["duplicate_intent_absent"] = not duplicate
    failures = [k.upper() for k, ok in gates.items() if not ok]
    return {"valid": not failures, "state": "VALIDATED" if not failures else "BLOCKED", "gates": gates, "failures": failures, "broker_health": broker, "kill_switch": kill}


def preview_order(context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    ctx = dict(context or {})
    intent = build_order_intent(ctx)
    validation = validate_order_intent(intent, ctx)
    with _LOCK:
        _STATE["metrics"]["preview_attempts"] += 1
        _STATE["intents"][intent["order_intent_id"]] = deepcopy(intent)
    if not validation["valid"]:
        return {"version": VERSION, "ok": False, "state": "BLOCKED", "intent": intent, "validation": validation, "live_submission_enabled": False}
    multiplier = max(1.0, _f(ctx.get("contract_multiplier"), 100.0))
    gross = intent["limit_price"] * intent["quantity"] * multiplier
    fees = round(_f(ctx.get("estimated_fees"), intent["quantity"] * 0.65), 2)
    slippage = round(_f(ctx.get("estimated_slippage"), gross * 0.005), 2)
    preview_id = str(uuid4())
    preview = {
        "preview_id": preview_id,
        "order_intent_id": intent["order_intent_id"],
        "state": "HUMAN_CONFIRMATION_REQUIRED",
        "estimated_debit_or_credit": round(gross, 2),
        "estimated_fees": fees,
        "estimated_slippage": slippage,
        "buying_power_effect": round(gross + fees + slippage, 2),
        "maximum_loss": intent["maximum_loss"] or round(gross + fees + slippage, 2),
        "maximum_gain": _f(ctx.get("maximum_gain"), 0.0),
        "breakeven": _f(ctx.get("breakeven"), 0.0),
        "portfolio_risk_after_fill": intent["portfolio_risk_after_fill"],
        "created_at": _now(),
        "expires_at": intent["expires_at"],
        "sandbox_only": True,
        "live_submission_enabled": False,
    }
    preview["preview_hash"] = _hash(preview)
    with _LOCK:
        _STATE["previews"][preview_id] = deepcopy(preview)
        _STATE["metrics"]["preview_successes"] += 1
    return {"version": VERSION, "ok": True, "state": preview["state"], "intent": intent, "validation": validation, "preview": preview}


def confirm_preview(preview_id: str, confirmation_text: str = "") -> Dict[str, Any]:
    with _LOCK:
        preview = deepcopy(_STATE["previews"].get(preview_id))
        kill = deepcopy(_STATE["kill_switch"])
    if not preview:
        return {"ok": False, "state": "NOT_FOUND", "error": "Preview not found"}
    if kill.get("active"):
        return {"ok": False, "state": "BLOCKED", "error": "Kill switch active"}
    if confirmation_text.strip().upper() not in {"CONFIRM", "CONFIRM PAPER", "CONFIRM SANDBOX"}:
        return {"ok": False, "state": "HUMAN_CONFIRMATION_REQUIRED", "error": "Explicit confirmation text required"}
    confirmation = {"confirmation_id": str(uuid4()), "preview_id": preview_id, "confirmed_at": _now(), "state": "CONFIRMED", "submission_state": "LOCKED_NO_BROKER_SUBMISSION", "live_submission_enabled": False}
    with _LOCK:
        _STATE["confirmations"][confirmation["confirmation_id"]] = deepcopy(confirmation)
    return {"ok": True, "confirmation": confirmation, "safety_note": "Confirmation certifies the preview only; Phase 30 has no live broker submission path."}


def cancel_preview(preview_id: str) -> Dict[str, Any]:
    with _LOCK:
        preview = _STATE["previews"].get(preview_id)
        if not preview:
            return {"ok": False, "state": "NOT_FOUND"}
        preview["state"] = "CANCELLED"
        preview["cancelled_at"] = _now()
        return {"ok": True, "preview": deepcopy(preview)}


def reconcile_execution(context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    ctx = dict(context or {})
    mismatches = []
    pairs = (("orders", "internal_orders", "broker_orders"), ("positions", "internal_positions", "broker_positions"), ("buying_power", "internal_buying_power", "broker_buying_power"))
    for label, internal_key, broker_key in pairs:
        if internal_key in ctx or broker_key in ctx:
            if ctx.get(internal_key) != ctx.get(broker_key):
                mismatches.append({"type": label.upper(), "internal": ctx.get(internal_key), "broker": ctx.get(broker_key)})
    status = "MATCHED" if not mismatches else "CRITICAL_MISMATCH"
    result = {"status": status, "checked_at": _now(), "mismatches": mismatches, "new_submissions_blocked": bool(mismatches)}
    with _LOCK:
        _STATE["reconciliation"] = deepcopy(result)
        if mismatches:
            _STATE["kill_switch"] = {"active": True, "scope": "GLOBAL", "reason": "RECONCILIATION_FAILURE", "changed_at": _now()}
    return result


def set_kill_switch(active: bool, reason: str = "MANUAL", scope: str = "GLOBAL") -> Dict[str, Any]:
    with _LOCK:
        _STATE["kill_switch"] = {"active": bool(active), "scope": str(scope or "GLOBAL").upper(), "reason": str(reason or "MANUAL").upper(), "changed_at": _now()}
        return deepcopy(_STATE["kill_switch"])


def build_execution_certification(context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    ctx = dict(context or {})
    broker = _broker_health(ctx)
    lineage = _m(ctx.get("data_lineage"))
    allocation = _m(ctx.get("portfolio_allocation"))
    command = _m(ctx.get("institutional_command_center") or ctx.get("command_center"))
    with _LOCK:
        state = deepcopy(_STATE)
    metrics = state["metrics"]
    preview_rate = metrics["preview_successes"] / metrics["preview_attempts"] * 100.0 if metrics["preview_attempts"] else 0.0
    reconciliation = state["reconciliation"]
    checks = {
        "broker_connectivity": broker["score"],
        "preview_reliability": preview_rate,
        "reconciliation_integrity": 100.0 if reconciliation["status"] == "MATCHED" else 0.0 if reconciliation["status"] == "CRITICAL_MISMATCH" else 50.0,
        "risk_compliance": 100.0 if allocation.get("allocation_state") != "BLOCKED" else 0.0,
        "lineage_completeness": _f(lineage.get("lineage_coverage_pct")),
        "system_health": _f(_m(command.get("system_confidence_index")).get("score"), 50.0),
        "kill_switch_readiness": 100.0,
        "live_execution_locked": 100.0,
    }
    score = round(sum(checks.values()) / len(checks), 1)
    if score >= 90 and metrics["paper_trades"] >= 20 and reconciliation["status"] == "MATCHED":
        readiness = "LIVE_REVIEW_REQUIRED"
    elif score >= 75 and broker["environment"] == "SANDBOX":
        readiness = "PAPER_CERTIFIED" if metrics["paper_trades"] >= 20 else "SANDBOX_READY"
    else:
        readiness = "NOT_READY"
    blockers = []
    if broker["status"] != "HEALTHY": blockers.append("BROKER_CERTIFICATION_INCOMPLETE")
    if state["kill_switch"]["active"]: blockers.append("KILL_SWITCH_ACTIVE")
    if reconciliation["status"] == "CRITICAL_MISMATCH": blockers.append("CRITICAL_RECONCILIATION_MISMATCH")
    if metrics["paper_trades"] < 20: blockers.append("PAPER_TRADE_SAMPLE_BELOW_20")
    return {
        "version": VERSION,
        "generated_at": _now(),
        "readiness_state": readiness,
        "readiness_score": score,
        "certification_checks": checks,
        "broker_health": broker,
        "reconciliation": reconciliation,
        "kill_switch": state["kill_switch"],
        "metrics": {**metrics, "preview_success_rate_pct": round(preview_rate, 1)},
        "blockers": blockers,
        "workflow_states": ["DRAFT", "VALIDATED", "PREVIEW_READY", "HUMAN_CONFIRMATION_REQUIRED", "CONFIRMED", "SUBMITTED", "ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED", "EXPIRED"],
        "controls": {"sandbox_preview": True, "paper_execution": True, "human_confirmation_required": True, "live_order_submission": False, "autonomous_execution": False, "risk_override": False},
        "safety_note": "Phase 30 certifies execution readiness but cannot submit live orders. Live execution remains structurally locked.",
    }
