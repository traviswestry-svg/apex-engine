"""APEX 65.6.1 — Monday readiness and critical-path validation.

Network- and broker-side-effect-free preflight. The Flask route supplies current
runtime telemetry, route/dependency facts, and local credential metadata. This
module performs a Python import smoke test for Monday-critical engine modules,
but never invokes an engine function, makes a network probe, previews an order,
or submits a broker order.
"""
from __future__ import annotations

from datetime import datetime, timezone
import importlib
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Set, Tuple

from engine.runtime_dependency_map import MONDAY_CRITICAL

SCHEMA_VERSION = "65.6.1"

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


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        try:
            parsed = datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (OverflowError, OSError, TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _credential_freshness_row(metadata: Optional[Mapping[str, Any]], *, now: datetime) -> Dict[str, Any]:
    meta = dict(metadata or {})
    issued_raw = meta.get("issued_at")
    refreshed_raw = meta.get("refreshed_at") or meta.get("updated_at")
    expires_raw = meta.get("expires_at")
    issued_at = _parse_timestamp(issued_raw)
    refreshed_at = _parse_timestamp(refreshed_raw)
    expires_at = _parse_timestamp(expires_raw)

    invalid_fields = []
    for key, raw, parsed in (("issued_at", issued_raw, issued_at), ("refreshed_at", refreshed_raw, refreshed_at), ("expires_at", expires_raw, expires_at)):
        if raw not in (None, "") and parsed is None:
            invalid_fields.append(key)

    reference = refreshed_at or issued_at
    age_seconds = max(0.0, (now - reference).total_seconds()) if reference else None
    seconds_to_expiry = (expires_at - now).total_seconds() if expires_at else None
    max_age_seconds = meta.get("max_age_seconds")
    warn_before_expiry_seconds = meta.get("warn_before_expiry_seconds", 7200)
    try:
        max_age_seconds = float(max_age_seconds) if max_age_seconds not in (None, "") else None
    except (TypeError, ValueError):
        max_age_seconds = None
        invalid_fields.append("max_age_seconds")
    try:
        warn_before_expiry_seconds = float(warn_before_expiry_seconds)
    except (TypeError, ValueError):
        warn_before_expiry_seconds = 7200.0
        invalid_fields.append("warn_before_expiry_seconds")

    freshness_state = "UNKNOWN"
    state = "PASS"
    detail = "Credential presence confirmed; local token-freshness metadata is not configured, so freshness is not asserted."
    if invalid_fields:
        freshness_state = "INVALID_METADATA"
        state = "WARN"
        detail = "Credential freshness metadata contains invalid timestamp/policy fields."
    elif expires_at is not None and seconds_to_expiry is not None and seconds_to_expiry <= 0:
        freshness_state = "EXPIRED"
        state = "WARN"
        detail = "Local E*TRADE token metadata indicates the credential is expired."
    elif expires_at is not None and seconds_to_expiry is not None and seconds_to_expiry <= warn_before_expiry_seconds:
        freshness_state = "EXPIRING_SOON"
        state = "WARN"
        detail = "Local E*TRADE token metadata indicates the credential is nearing expiry."
    elif reference is not None and max_age_seconds is not None and age_seconds is not None and age_seconds > max_age_seconds:
        freshness_state = "STALE"
        state = "WARN"
        detail = "Local E*TRADE token metadata exceeds the configured maximum age."
    elif reference is not None or expires_at is not None:
        freshness_state = "FRESH"
        state = "PASS"
        detail = "Local E*TRADE token freshness metadata is within configured limits."

    return _row(
        "broker_credential_freshness", "E*TRADE credential freshness", state, required=False, detail=detail,
        data={
            "freshness_state": freshness_state,
            "metadata_available": bool(reference or expires_at),
            "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
            "seconds_to_expiry": round(seconds_to_expiry, 3) if seconds_to_expiry is not None else None,
            "issued_at": issued_at.isoformat() if issued_at else None,
            "refreshed_at": refreshed_at.isoformat() if refreshed_at else None,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "max_age_seconds": max_age_seconds,
            "warn_before_expiry_seconds": warn_before_expiry_seconds,
            "invalid_fields": sorted(set(invalid_fields)),
            "source": str(meta.get("source") or "local_metadata"),
            "network_probe_performed": False,
        },
    )


def _import_smoke_row(modules: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    module_names = sorted(set(MONDAY_CRITICAL if modules is None else modules) - {"app"})
    imported = []
    failures = []
    for module_name in module_names:
        try:
            importlib.import_module(module_name)
            imported.append(module_name)
        except Exception as exc:
            failures.append({
                "module": module_name,
                "error_type": type(exc).__name__,
                "error": str(exc)[:240],
            })
    return _row(
        "critical_import_smoke", "Monday-critical import smoke", "FAIL" if failures else "PASS",
        detail=(f"{len(failures)} Monday-critical module import(s) failed." if failures else f"Imported {len(imported)} Monday-critical modules successfully."),
        data={"total": len(module_names), "imported": imported, "failures": failures, "application_root_already_loaded": True, "network_probe_performed": False},
    )


def build_monday_readiness(
    *,
    version: str,
    runtime_health: Mapping[str, Any],
    dependency_map: Mapping[str, Any],
    registered_routes: Iterable[Tuple[str, str]],
    tv_webhook_secret_configured: bool,
    broker_credentials_configured: bool,
    live_trading_enabled: bool,
    broker_credential_freshness: Optional[Mapping[str, Any]] = None,
    critical_import_modules: Optional[Sequence[str]] = None,
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

    # Static graph reachability is not enough: prove each critical module can be
    # imported in the deployed interpreter. This performs Python imports only;
    # it does not invoke engines, routes, broker methods, or network probes.
    checks.append(_import_smoke_row(critical_import_modules))

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
    if not scanner:
        scanner_check = "FAIL"
    elif market_open:
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
    if not engines:
        engine_check = "FAIL"
    elif market_open:
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
    if not td:
        td_check = "FAIL"
    elif market_open:
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
    checks.append(_credential_freshness_row(broker_credential_freshness, now=_parse_timestamp(generated_at) or datetime.now(timezone.utc)))
    checks.append(_row(
        "live_execution_switch", "E*TRADE live-trading kill switch", "PASS" if live_trading_enabled else "INFO",
        required=False,
        detail="Live execution is armed." if live_trading_enabled else "ETRADE_ENABLE_TRADING is false by policy; preview path is available and live order submission remains disarmed.",
        data={"live_trading_enabled": bool(live_trading_enabled), "execution_armed": bool(live_trading_enabled)},
    ))

    failures = [c for c in checks if c["required"] and c["state"] == "FAIL"]
    warnings = [c for c in checks if c["state"] == "WARN"]
    standby = [c for c in checks if c["state"] == "STANDBY"]
    info = [c for c in checks if c["state"] == "INFO"]
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
            "info": len(info),
            "fail": len(failures),
        },
        "blockers": [{"step": c["step"], "detail": c["detail"]} for c in failures],
        "warnings": [{"step": c["step"], "detail": c["detail"]} for c in warnings],
        "checks": checks,
        "safety": {
            "network_io_performed": False,
            "imports_performed": True,
            "engines_invoked": False,
            "broker_preview_invoked": False,
            "broker_order_submitted": False,
        },
    }
