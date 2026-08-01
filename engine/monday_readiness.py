"""APEX 65.6 — Monday readiness and critical-path validation.

Pure, side-effect-free aggregation. The Flask route supplies current runtime
telemetry, registered routes, dependency-map facts, and configuration booleans.
This module never performs network I/O, invokes a trading engine, or submits /
previews a broker order.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Set, Tuple

SCHEMA_VERSION = "65.6"

# method/path contracts that must exist for the Monday SPX decision/execution path.
CRITICAL_ROUTE_STEPS: Sequence[Tuple[str, str, str, str]] = (
    ("signal_ingest", "TradingView / Pine signal ingest", "POST", "/tv_signal"),
    ("market_memory", "Trade Director Market Memory", "GET", "/api/position/market-memory"),
    ("cross_asset", "Trade Director Cross-Asset Intelligence", "GET", "/api/position/cross-asset-intelligence"),
    ("strategy_orchestration", "Trade Director Strategy Orchestration", "GET", "/api/position/strategy-orchestration"),
    ("evidence", "Institutional Evidence", "GET", "/api/evidence/status"),
    ("execution_readiness", "Broker-neutral Execution Readiness", "GET", "/api/position/execution-readiness"),
    ("contract_selection", "SPX Recommended Contracts", "GET", "/api/trade/spx/recommended-contracts"),
    ("execution_preview", "SPX Entry Preview", "POST", "/api/trade/spx/preview-entry"),
    ("execution_gateway", "SPX Order Gateway", "POST", "/api/trade/spx/place-entry"),
)


def _row(step: str, label: str, state: str, *, required: bool = True, detail: str = "", data: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    return {
        "step": step,
        "label": label,
        "state": state,
        "required": bool(required),
        "detail": str(detail or ""),
        "data": dict(data or {}),
    }


def _runtime_component(runtime_health: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    for rec in runtime_health.get("components") or []:
        if isinstance(rec, Mapping) and rec.get("name") == name:
            return rec
    return {}


def build_monday_readiness(
    *,
    version: str,
    runtime_health: Mapping[str, Any],
    dependency_map: Mapping[str, Any],
    registered_routes: Iterable[Tuple[str, str]],
    tv_webhook_secret_configured: bool,
    broker_credentials_configured: bool,
    live_trading_enabled: bool,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    routes: Set[Tuple[str, str]] = {(str(m).upper(), str(p)) for m, p in registered_routes}
    session = str(runtime_health.get("session") or "UNKNOWN").upper()
    market_open = session == "MARKET_OPEN"

    checks = []

    # Runtime foundation.
    runtime_ready = bool(runtime_health.get("runtime_ready"))
    checks.append(_row(
        "runtime_foundation", "Runtime foundation", "PASS" if runtime_ready else "FAIL",
        detail=str(runtime_health.get("tradeability_reason") or ""),
        data={"runtime_status": runtime_health.get("status"), "blockers": runtime_health.get("blockers") or [], "warnings": runtime_health.get("warnings") or []},
    ))

    # Monday critical engine reachability from the generated dependency graph.
    dep_summary = dependency_map.get("summary") or {}
    critical_missing = list(dep_summary.get("monday_critical_missing") or [])
    critical_not_active = list(dep_summary.get("monday_critical_not_active") or [])
    engines_ok = not critical_missing and not critical_not_active
    checks.append(_row(
        "critical_engines", "Monday-critical engine graph", "PASS" if engines_ok else "FAIL",
        detail="All Monday-critical engines are present and ACTIVE." if engines_ok else "Critical engine graph is incomplete.",
        data={"missing": critical_missing, "not_active": critical_not_active},
    ))

    # Signal authentication must be configured even though /tv_signal is exempt
    # from app-wide auth because it owns its HMAC/shared-secret gate.
    checks.append(_row(
        "tradingview_auth", "TradingView webhook authentication", "PASS" if tv_webhook_secret_configured else "FAIL",
        detail="TV webhook secret configured." if tv_webhook_secret_configured else "TV_WEBHOOK_SECRET/TRADINGVIEW_SECRET is not configured.",
    ))

    # Registered route contract: presence only. Never invoke POSTs here.
    for step, label, method, path in CRITICAL_ROUTE_STEPS:
        present = (method, path) in routes
        checks.append(_row(
            f"route:{step}", label, "PASS" if present else "FAIL",
            detail=f"{method} {path} {'registered' if present else 'MISSING'}.",
            data={"method": method, "path": path, "invoked": False},
        ))

    # Market/data/engine behavior uses existing telemetry only.
    scanner = _runtime_component(runtime_health, "Scanner / Freshness")
    scanner_state = str(scanner.get("state") or "UNAVAILABLE")
    if market_open:
        scanner_check = "PASS" if scanner_state == "HEALTHY" else ("WARN" if scanner_state in {"DEGRADED", "STALE"} else "FAIL")
    else:
        scanner_check = "STANDBY" if scanner_state == "HEALTHY" else "WARN"
    checks.append(_row(
        "scanner_live_cycle", "Scanner / market freshness", scanner_check,
        detail="Live scanner required and evaluated." if market_open else "Market closed; live scanner evaluation deferred until session open.",
        data=dict(scanner.get("data") or {}),
    ))

    engines = _runtime_component(runtime_health, "Institutional Engines")
    engine_state = str(engines.get("state") or "UNAVAILABLE")
    if market_open:
        engine_check = "PASS" if engine_state == "HEALTHY" else ("WARN" if engine_state in {"DEGRADED", "STALE"} else "FAIL")
    else:
        engine_check = "STANDBY" if engine_state == "HEALTHY" else "WARN"
    checks.append(_row(
        "institutional_engine_cycle", "Institutional engine live cycle", engine_check,
        detail="Live institutional engine cycle evaluated." if market_open else "Market closed; engines are expected to remain in standby until a live scan.",
        data=dict(engines.get("data") or {}),
    ))

    td = _runtime_component(runtime_health, "Trade Director Intelligence")
    td_state = str(td.get("state") or "UNAVAILABLE")
    if market_open:
        td_check = "PASS" if td_state == "HEALTHY" else ("WARN" if td_state in {"DEGRADED", "STALE"} else "FAIL")
    else:
        td_check = "STANDBY" if td_state == "HEALTHY" else "WARN"
    checks.append(_row(
        "trade_director_live_cycle", "Market Memory → Cross-Asset → Strategy Orchestration", td_check,
        detail="Trade Director intelligence evaluated for the live session." if market_open else "Available; live-session evaluation pending.",
        data=dict(td.get("data") or {}),
    ))

    # Broker configuration is required for an executable Monday path. Whether
    # live trading is armed is reported separately and never auto-changed here.
    checks.append(_row(
        "broker_credentials", "E*TRADE execution credentials", "PASS" if broker_credentials_configured else "FAIL",
        detail="Required E*TRADE credential fields are configured." if broker_credentials_configured else "One or more required E*TRADE credential fields are missing.",
    ))
    checks.append(_row(
        "live_execution_switch", "E*TRADE live-trading kill switch", "PASS" if live_trading_enabled else "WARN",
        required=False,
        detail="Live execution is armed." if live_trading_enabled else "ETRADE_ENABLE_TRADING is false; preview path remains safe but live order submission is disarmed.",
        data={"live_trading_enabled": bool(live_trading_enabled)},
    ))

    failures = [c for c in checks if c["required"] and c["state"] == "FAIL"]
    warnings = [c for c in checks if c["state"] == "WARN"]
    standby = [c for c in checks if c["state"] == "STANDBY"]
    monday_ready = not failures

    if failures:
        status = "BLOCKED"
    elif warnings:
        status = "READY_WITH_WARNINGS"
    elif standby:
        status = "PREFLIGHT_PASS_LIVE_VALIDATION_PENDING"
    else:
        status = "READY"

    return {
        "ok": monday_ready,
        "schema_version": SCHEMA_VERSION,
        "version": version,
        "generated_at": generated_at,
        "status": status,
        "monday_ready": monday_ready,
        "session": session,
        "validation_mode": "LIVE_SESSION" if market_open else "STATIC_PREFLIGHT",
        "live_validation_pending": bool(not market_open and standby),
        "execution_mode": "LIVE_ARMED" if live_trading_enabled else "PREVIEW_ONLY",
        "summary": {
            "total_checks": len(checks),
            "pass": sum(1 for c in checks if c["state"] == "PASS"),
            "standby": len(standby),
            "warn": len(warnings),
            "fail": len(failures),
        },
        "blockers": [{"step": c["step"], "detail": c["detail"]} for c in failures],
        "warnings": [{"step": c["step"], "detail": c["detail"]} for c in warnings],
        "checks": checks,
        "safety": {
            "network_io_performed": False,
            "engines_invoked": False,
            "broker_preview_invoked": False,
            "broker_order_submitted": False,
        },
    }
