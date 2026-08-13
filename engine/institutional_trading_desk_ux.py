"""APEX 17.1 Institutional Trading Desk UX aggregation layer.

Read-only presentation model for the professional desk workspace.  It composes
existing governed engines without mutating recommendations, risk, positions, or
broker state.
"""
from __future__ import annotations

from typing import Any, Callable

from . import institutional_autonomous_desk as iad
from . import live_mission_control as lmc
from . import performance_intelligence as pi
from . import broker_synchronized_position_state as bsps
from . import adaptive_intelligence as ai18

VERSION = "17.1_INSTITUTIONAL_TRADING_DESK_UX"


def _safe(fn: Callable[[], Any], fallback: Any) -> Any:
    try:
        value = fn()
        return value if value is not None else fallback
    except Exception as exc:  # presentation layer must degrade, never crash desk
        if isinstance(fallback, dict):
            return {**fallback, "status": "UNAVAILABLE", "error": str(exc)}
        return fallback


def _score(value: Any, default: int = 0) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def _decision_ribbon(mission: dict, broker: dict) -> list[dict]:
    p = mission.get("institutional_pressure") or {}
    m = mission.get("market_state") or {}
    pb = mission.get("playbook") or {}
    c = mission.get("institutional_confluence") or {}
    risk = mission.get("portfolio_risk") or {}
    live = mission.get("live_operations") or {}
    latest = broker.get("latest") or {}
    safety = mission.get("confirmation_gated_execution") or {}
    return [
        {"key": "market", "label": "Market", "value": m.get("active_state") or "COLLECTING"},
        {"key": "pressure", "label": "Pressure", "value": p.get("bias") or "COLLECTING", "score": _score(p.get("institutional_pressure_score"))},
        {"key": "playbook", "label": "Playbook", "value": pb.get("active_playbook") or "STAND_DOWN"},
        {"key": "confidence", "label": "Confidence", "value": _score(c.get("institutional_confluence_score"))},
        {"key": "risk", "label": "Risk", "value": risk.get("risk_state") or "UNKNOWN"},
        {"key": "permission", "label": "Permission", "value": live.get("tradeability") or "NOT_TRADEABLE"},
        {"key": "broker", "label": "Broker", "value": latest.get("sync_state") or "BROKER_UNAVAILABLE"},
        {"key": "execution", "label": "Execution", "value": "CONFIRMATION_GATED" if (safety.get("safety") or {}).get("runtime_execution_enabled") else "BLOCKED"},
    ]


def _evidence(mission: dict) -> list[dict]:
    c = mission.get("institutional_confluence") or {}
    rows = []
    for component in c.get("components") or []:
        rows.append({
            "name": str(component.get("name") or "Evidence"),
            "score": _score(component.get("score")),
            "weight": round(float(component.get("weight") or 0) * 100, 1),
            "available": bool(component.get("available")),
        })
    # Stable fallback cards make missing data explicit rather than inventing it.
    if not rows:
        rows = [{"name": n, "score": 0, "weight": 0, "available": False} for n in
                ("Market State", "Order Flow", "Gamma", "Auction", "Structure", "Liquidity", "Risk")]
    return rows


def _timeline(active_trade: dict | None) -> list[dict]:
    if not active_trade:
        return []
    tid = active_trade.get("desk_trade_id")
    if not tid:
        return []
    detail = _safe(lambda: iad.timeline(tid), {"events": []})
    return [{
        "sequence": e.get("sequence_no"),
        "state": e.get("to_state"),
        "from_state": e.get("from_state"),
        "event_type": e.get("event_type"),
        "actor": e.get("actor"),
        "observed_at": e.get("observed_at"),
        "evidence": e.get("evidence") or {},
    } for e in detail.get("events") or []]


def status() -> dict:
    return {
        "status": "READY",
        "engine": "INSTITUTIONAL_TRADING_DESK_UX",
        "build_version": VERSION,
        "read_only": True,
        "workspace_persistence": "BROWSER_LOCAL_ONLY",
        "automatic_order_submission_enabled": False,
        "human_confirmation_required": True,
        "production_effect": "NONE",
    }


def workspace(symbol: str = "SPX") -> dict:
    symbol = str(symbol or "SPX").upper()
    mission = _safe(lambda: lmc.dashboard(symbol), {"status": "UNAVAILABLE"})
    desk = _safe(lambda: iad.dashboard(25), {"active_trades": [], "recent_trades": []})
    broker = _safe(lambda: bsps.dashboard("PRIMARY", "ETRADE"), {"latest": {}})
    performance = _safe(lambda: pi.dashboard(symbol), {"analysis": {}})
    active = (desk.get("active_trades") or [None])[0]
    return {
        "ok": True,
        "status": "READY",
        "symbol": symbol,
        "version": VERSION,
        "adaptive_intelligence": _safe(lambda: ai18.dashboard(symbol), {"status": "UNAVAILABLE"}),
        "ribbon": _decision_ribbon(mission, broker),
        "mission_control": mission,
        "evidence": _evidence(mission),
        "active_trade": active,
        "trade_timeline": _timeline(active),
        "recent_trades": desk.get("recent_trades") or [],
        "performance": performance,
        "broker_sync": broker,
        "command_palette": [
            {"id": "refresh", "label": "Refresh Mission Control", "shortcut": "R"},
            {"id": "timeline", "label": "Show Trade Timeline", "shortcut": "T"},
            {"id": "evidence", "label": "Open Evidence Explorer", "shortcut": "E"},
            {"id": "explain", "label": "Explain Current Decision", "shortcut": "X"},
            {"id": "performance", "label": "Open Performance Center", "shortcut": "P"},
            {"id": "broker", "label": "Open Broker Health", "shortcut": "B"},
        ],
        "safety": status(),
    }
