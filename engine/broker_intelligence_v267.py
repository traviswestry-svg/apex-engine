"""APEX 26.7 — Broker Intelligence (advisory, PREVIEW/READ-ONLY).

Surfaces broker context for Power E*TRADE, Interactive Brokers, and thinkorswim:
connectivity/health, order preview economics (buying power, margin, commission,
estimated cost), and order/fill status. It normalizes broker data for display.

Safety contract (non-negotiable)
--------------------------------
* This engine has NO order-submission path. It never calls ``place_order`` and
  imports no placement capability. It only reads/normalizes and reports.
* Real order placement stays on the repository's existing confirmation-gated
  execution route (``engine/execution/trade_routes``). This engine reports the
  gate status; it does not bypass or replace it.
* ``production_effect`` is ``NONE`` and ``submits_orders`` is ``False`` always.
"""
from __future__ import annotations

import os
from typing import Any, Mapping, Optional

VERSION = "26.7.0_BROKER_INTELLIGENCE"
SCHEMA_VERSION = "apex.broker_intelligence.v267.v1"

SUPPORTED_BROKERS = ("power_etrade", "interactive_brokers", "thinkorswim")
ORDER_STATES = ("NONE", "PREVIEW", "WORKING", "PARTIAL", "FILLED", "REJECTED", "CANCELLED")


def _number(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _confirmation_gated() -> bool:
    # Reflects the real execution gate. When the authoritative kill switch
    # (ETRADE_ENABLE_TRADING) is off, execution is fully gated (fail-safe). When
    # it is on, gating follows APEX_CONFIRMATION_GATED_EXECUTION_ENABLED.
    trading_enabled = _text(os.getenv("ETRADE_ENABLE_TRADING", "false")).lower() == "true"
    if not trading_enabled:
        return True
    return _text(os.getenv("APEX_CONFIRMATION_GATED_EXECUTION_ENABLED", "false")).lower() == "true"


def _etrade_health() -> dict[str, Any]:
    """Read-only health probe of the existing E*TRADE adapter (no network in tests)."""
    try:
        from .brokers.etrade_adapter import ETradeAdapter  # type: ignore
        adapter = ETradeAdapter()
        configured = bool(adapter.configured()) if hasattr(adapter, "configured") else False
        mode = getattr(adapter, "mode", "sandbox")
        trading_enabled = _text(os.getenv("ETRADE_ENABLE_TRADING", "false")).lower() == "true"
        return {"configured": configured, "mode": mode, "trading_enabled": trading_enabled,
                "state": "CONNECTED" if configured else "NOT_CONFIGURED"}
    except Exception:
        return {"configured": False, "mode": "unknown", "trading_enabled": False,
                "state": "NOT_CONFIGURED"}


def broker_health() -> dict[str, Any]:
    brokers = {"power_etrade": _etrade_health()}
    # IBKR and thinkorswim adapters are not present in this build.
    for name in ("interactive_brokers", "thinkorswim"):
        brokers[name] = {"configured": False, "mode": "unknown", "trading_enabled": False,
                         "state": "NOT_CONFIGURED"}
    return brokers


def normalize_preview(preview: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Normalize a broker preview/account payload into display fields.

    The preview is supplied by the caller (e.g. the response from the existing
    confirmation-gated ``/api/trade/spx/preview-*`` route or an account snapshot).
    This function does not fetch or place anything.
    """
    p = _mapping(preview)
    account = _mapping(p.get("account"))
    order = _mapping(p.get("order"))
    status = _text(order.get("status") or p.get("order_status")).upper() or "NONE"
    if status not in ORDER_STATES:
        status = "NONE"
    return {
        "buying_power": _number(account.get("buying_power") or p.get("buying_power")),
        "margin": _number(account.get("margin") or p.get("margin")),
        "commission": _number(order.get("commission") or p.get("commission")),
        "estimated_cost": _number(order.get("estimated_cost") or p.get("estimated_cost")),
        "order_status": status,
        "fill_status": _text(order.get("fill_status") or p.get("fill_status")) or None,
        "reject_reason": _text(order.get("reject_reason") or p.get("reject_reason")) or None,
        "latency_ms": _number(p.get("latency_ms")),
    }


def build_broker_view(payload: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    root = payload if isinstance(payload, Mapping) else {}
    preview = root.get("broker_preview") or root.get("preview")
    health = broker_health()
    selected = _text(root.get("broker") or "power_etrade").lower()
    if selected not in SUPPORTED_BROKERS:
        selected = "power_etrade"

    return {
        "ok": True,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "selected_broker": selected,
        "supported_brokers": list(SUPPORTED_BROKERS),
        "broker_health": health,
        "preview": normalize_preview(preview) if preview else None,
        "execution_gate": {
            "confirmation_required": _confirmation_gated(),
            "placement_route": "engine/execution/trade_routes (/api/trade/spx/*)",
            "note": "Broker Intelligence is read/preview only. Placement is confirmation-gated "
                    "on the existing route; this engine cannot submit an order.",
        },
        "submits_orders": False,
        "production_effect": "NONE",
    }


def status() -> dict[str, Any]:
    return {
        "status": "READY",
        "engine": "BROKER_INTELLIGENCE",
        "version": VERSION,
        "supported_brokers": list(SUPPORTED_BROKERS),
        "order_states": list(ORDER_STATES),
        "confirmation_required": _confirmation_gated(),
        "submits_orders": False,
        "read_only": True,
        "production_effect": "NONE",
    }
