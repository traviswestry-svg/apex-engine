"""Shared, dependency-light contracts for the integrated Trade Director lifecycle.

These helpers normalize already-cached engine outputs into one context envelope.
They intentionally perform no I/O, provider requests, broker calls, persistence,
or startup work.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def normalize_trade_context(context: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    c = dict(context or {})
    return {
        "symbol": c.get("symbol") or c.get("ticker") or as_mapping(c.get("position")).get("ticker") or "SPX",
        "as_of": c.get("checked_at") or c.get("as_of") or utc_now_iso(),
        "session": dict(as_mapping(c.get("session_intelligence"))),
        "market_memory": dict(as_mapping(c.get("market_memory"))),
        "cross_asset": dict(as_mapping(c.get("cross_asset_intelligence"))),
        "strategy": dict(as_mapping(c.get("strategy_orchestration"))),
        "contract": dict(as_mapping(c.get("options_intelligence"))),
        "execution": dict(as_mapping(c.get("execution_desk"))),
        "multi_timeframe": dict(as_mapping(c.get("multi_timeframe_intelligence"))),
        "institutional_flow": dict(as_mapping(c.get("flow_intelligence"))),
        "decision_intelligence": dict(as_mapping(c.get("decision_intelligence"))),
        "decision": dict(as_mapping(c.get("institutional_decision_engine"))),
        "position": dict(as_mapping(c.get("position"))),
        "risk": dict(as_mapping(c.get("risk") or c.get("execution_readiness"))),
        "trade_health": dict(as_mapping(c.get("trade_health"))),
        "raw": c,
    }
