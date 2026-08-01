"""APEX 65.2 — canonical runtime health aggregation.

Pure helpers only.  The Flask route supplies already-known runtime facts so this
module never performs network I/O, starts scans, or invokes trading engines.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

RUNTIME_STATES = ("HEALTHY", "DEGRADED", "STALE", "UNAVAILABLE", "DISABLED", "FAILED")
_STATE_RANK = {name: idx for idx, name in enumerate(RUNTIME_STATES)}


def normalize_state(value: Any, *, default: str = "UNAVAILABLE") -> str:
    raw = str(value or "").strip().upper()
    aliases = {
        "OK": "HEALTHY", "READY": "HEALTHY", "PASS": "HEALTHY", "LIVE": "HEALTHY", "GREEN": "HEALTHY", "CLOSED": "HEALTHY", "SCHEDULED_IDLE": "HEALTHY",
        "WARN": "DEGRADED", "WARNING": "DEGRADED", "YELLOW": "DEGRADED", "PARTIAL": "DEGRADED", "WARMING": "DEGRADED",
        "RED": "FAILED", "ERROR": "FAILED", "MISSING": "UNAVAILABLE", "OFFLINE": "UNAVAILABLE",
        "NOT_AVAILABLE": "UNAVAILABLE", "NOT_YET_COMPUTED": "UNAVAILABLE",
    }
    state = aliases.get(raw, raw)
    return state if state in RUNTIME_STATES else default


def worst_state(states: Iterable[Any]) -> str:
    normalized = [normalize_state(v) for v in states]
    if not normalized:
        return "UNAVAILABLE"
    # FAILED is worst; DISABLED is intentional and should not make an otherwise
    # healthy runtime fail, so score it between UNAVAILABLE and FAILED only when
    # it is the sole/explicit state supplied.
    severity = {"HEALTHY": 0, "DISABLED": 0, "STALE": 1, "DEGRADED": 2, "UNAVAILABLE": 3, "FAILED": 4}
    return max(normalized, key=lambda s: severity[s])


def component(name: str, state: Any, *, required: bool = True, detail: str = "", data: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    normalized = normalize_state(state)
    return {
        "name": name,
        "state": normalized,
        "required": bool(required),
        "detail": str(detail or ""),
        "data": dict(data or {}),
    }


def build_runtime_health(
    *,
    version: str,
    route_audit: Mapping[str, Any],
    scanner: Mapping[str, Any],
    sources: Mapping[str, Any],
    engine_health: Mapping[str, Any],
    trade_director: Mapping[str, Any],
    auth_layer_available: bool,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()

    route_state = normalize_state(route_audit.get("status"), default="FAILED")
    auth_state = "HEALTHY" if auth_layer_available else "FAILED"
    scanner_state = normalize_state(scanner.get("state") or scanner.get("health_state"))

    source_rows = []
    for name, record in sorted((sources or {}).items()):
        if isinstance(record, Mapping):
            s = normalize_state(record.get("state") or record.get("status"), default="UNAVAILABLE")
            available = record.get("available")
            if available is True and s == "UNAVAILABLE":
                s = "HEALTHY"
            source_rows.append(component(str(name), s, required=False, detail=str(record.get("detail") or record.get("error") or ""), data=record))
        else:
            source_rows.append(component(str(name), "HEALTHY" if record else "UNAVAILABLE", required=False))
    source_state = worst_state([r["state"] for r in source_rows]) if source_rows else "UNAVAILABLE"

    red = int(engine_health.get("red") or 0)
    yellow = int(engine_health.get("yellow") or 0)
    available = int(engine_health.get("available") or 0)
    total = int(engine_health.get("total") or 0)
    engines_expected = bool(engine_health.get("expected", True))
    if not engines_expected and not available:
        engines_state = "HEALTHY"
    elif red:
        engines_state = "FAILED"
    elif yellow:
        engines_state = "DEGRADED"
    elif total and available:
        engines_state = "HEALTHY"
    else:
        engines_state = "UNAVAILABLE"

    td_components = []
    for key, label in (
        ("market_memory", "Market Memory"),
        ("cross_asset_intelligence", "Cross-Asset Intelligence"),
        ("strategy_orchestration", "Strategy Orchestration"),
    ):
        rec = trade_director.get(key) or {}
        if not isinstance(rec, Mapping):
            rec = {}
        state = normalize_state(rec.get("state") or rec.get("status"))
        td_components.append(component(label, state, required=True, detail=str(rec.get("detail") or ""), data=rec))
    td_state = worst_state(c["state"] for c in td_components)

    components = [
        component("Authentication", auth_state, required=True, data={"available": bool(auth_layer_available)}),
        component("Route Integrity", route_state, required=True, data={
            "duplicate_route_count": route_audit.get("duplicate_route_count"),
            "critical_missing": route_audit.get("critical_missing") or [],
            "route_count": route_audit.get("route_count"),
        }),
        component("Scanner / Freshness", scanner_state, required=True, detail=str(scanner.get("detail") or scanner.get("health_detail") or ""), data=scanner),
        component("Market Data Sources", source_state, required=False, data={"sources": source_rows}),
        component("Institutional Engines", engines_state, required=True, detail="Scheduled standby; no live scan required." if not engines_expected and not available else "", data={"red": red, "yellow": yellow, "available": available, "total": total, "expected": engines_expected}),
        component("Trade Director Intelligence", td_state, required=True, data={"components": td_components}),
    ]

    required_states = [c["state"] for c in components if c["required"]]
    overall = worst_state(required_states)
    blockers = [c["name"] for c in components if c["required"] and c["state"] in {"FAILED", "UNAVAILABLE"}]
    warnings = [c["name"] for c in components if c["state"] in {"DEGRADED", "STALE"}]

    session = str(scanner.get("session") or "").strip().upper()
    runtime_ready = overall not in {"FAILED", "UNAVAILABLE"} and not blockers
    tradeable_runtime = runtime_ready and overall == "HEALTHY" and session == "MARKET_OPEN"
    if not runtime_ready:
        tradeability_reason = "RUNTIME_BLOCKED"
    elif overall != "HEALTHY":
        tradeability_reason = "RUNTIME_DEGRADED"
    elif session != "MARKET_OPEN":
        tradeability_reason = "MARKET_CLOSED"
    else:
        tradeability_reason = "READY"

    return {
        "ok": runtime_ready,
        "status": overall,
        "version": version,
        "generated_at": generated_at,
        "runtime_ready": runtime_ready,
        "tradeable_runtime": tradeable_runtime,
        "tradeability_reason": tradeability_reason,
        "session": session or None,
        "blockers": blockers,
        "warnings": warnings,
        "components": components,
    }
