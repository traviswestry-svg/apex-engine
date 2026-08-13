"""APEX 18.0.5 dependency and service governance.

Read-only service inventory, runtime observations, severity-aware readiness, and
an opt-in circuit-breaker utility. It does not place orders, mutate broker state,
or alter trade decisions.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple, TypeVar

from .release_manager import APP_VERSION

T = TypeVar("T")
UTC = timezone.utc

@dataclass(frozen=True)
class DependencyDefinition:
    name: str
    category: str
    criticality: str
    credential_variables: Tuple[str, ...]
    timeout_variable: Optional[str]
    default_timeout_seconds: float
    retry_limit: int
    circuit_failure_threshold: int
    circuit_recovery_seconds: int
    required_when: str
    description: str
    failover: Optional[str] = None

REGISTRY: Dict[str, DependencyDefinition] = {
    d.name: d for d in (
        DependencyDefinition("database", "DATABASE", "CRITICAL", ("DATABASE_URL", "DB_PATH"), None, 5.0, 1, 3, 30, "always; local DB_PATH fallback supported", "Primary persistence layer"),
        DependencyDefinition("polygon_massive", "MARKET_DATA", "CRITICAL", ("POLYGON_API_KEY", "MASSIVE_API_KEY"), "SOURCE_TIMEOUT_SECONDS", 8.0, 2, 4, 45, "live market-data operation", "Polygon/Massive market data", "configured alternate market-data source"),
        DependencyDefinition("quantdata", "MARKET_DATA", "IMPORTANT", ("QUANTDATA_API_KEY", "QUANTDATA_TOKEN"), "SOURCE_TIMEOUT_SECONDS", 8.0, 2, 4, 60, "institutional options-flow features enabled", "QuantData options-flow provider", "continue with reduced flow completeness"),
        DependencyDefinition("benzinga", "NEWS", "OPTIONAL", ("BENZINGA_API_KEY", "BENZINGA_TOKEN"), "SOURCE_TIMEOUT_SECONDS", 8.0, 1, 4, 120, "Benzinga/news features enabled", "Benzinga news provider", "continue without provider-specific news"),
        DependencyDefinition("telegram", "MESSAGING", "OPTIONAL", ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"), "SOURCE_TIMEOUT_SECONDS", 8.0, 1, 4, 120, "Telegram notifications enabled", "Telegram alert delivery", "retain alerts in application surfaces"),
        DependencyDefinition("etrade", "BROKER", "SAFETY_CRITICAL", ("ETRADE_CONSUMER_KEY", "ETRADE_CONSUMER_SECRET", "ETRADE_ACCESS_TOKEN", "ETRADE_ACCESS_TOKEN_SECRET", "ETRADE_ACCOUNT_ID"), "SOURCE_TIMEOUT_SECONDS", 10.0, 0, 2, 120, "broker preview or mutation enabled", "E*TRADE preview/submission adapter", "fail closed; no broker mutation"),
        DependencyDefinition("render_runtime", "DEPLOYMENT", "IMPORTANT", ("APEX_BUILD_ID", "RENDER_DEPLOY_ID"), None, 1.0, 0, 3, 60, "hosted production deployment", "Render deployment metadata and runtime", "operate with unknown deployment metadata"),
        DependencyDefinition("scanner", "SCANNER", "CRITICAL", tuple(), "SCANNER_HEARTBEAT_SECONDS", 30.0, 0, 3, 60, "scanner enabled", "APEX scanner lifecycle and heartbeat"),
    )
}

_lock = threading.RLock()
_observations: Dict[str, Dict[str, Any]] = {}
_breakers: Dict[str, Dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _configured(names: Iterable[str], env: Mapping[str, str]) -> bool:
    names = tuple(names)
    if not names:
        return True
    return any(bool(str(env.get(n, "")).strip()) for n in names)


def _timeout(defn: DependencyDefinition, env: Mapping[str, str]) -> float:
    if not defn.timeout_variable:
        return defn.default_timeout_seconds
    raw = env.get(defn.timeout_variable)
    try:
        value = float(raw) if raw not in (None, "") else defn.default_timeout_seconds
        return value if value > 0 else defn.default_timeout_seconds
    except (TypeError, ValueError):
        return defn.default_timeout_seconds


def record_observation(name: str, *, ok: bool, latency_ms: Optional[float] = None,
                       error: Optional[str] = None, observed_at: Optional[str] = None) -> None:
    """Record sanitized dependency telemetry. Error text is deliberately bounded."""
    if name not in REGISTRY:
        return
    with _lock:
        prior = _observations.get(name, {})
        _observations[name] = {
            "ok": bool(ok),
            "latency_ms": round(float(latency_ms), 3) if latency_ms is not None else None,
            "last_success_at": (observed_at or _now()) if ok else prior.get("last_success_at"),
            "last_failure_at": (observed_at or _now()) if not ok else prior.get("last_failure_at"),
            "error": (str(error)[:240] if error else None),
            "observed_at": observed_at or _now(),
        }


def _breaker(name: str) -> Dict[str, Any]:
    with _lock:
        return _breakers.setdefault(name, {"state": "CLOSED", "failures": 0, "opened_at_monotonic": None})


def circuit_state(name: str) -> Dict[str, Any]:
    d = REGISTRY[name]
    with _lock:
        b = dict(_breaker(name))
    if b["state"] == "OPEN" and b["opened_at_monotonic"] is not None:
        elapsed = time.monotonic() - b["opened_at_monotonic"]
        if elapsed >= d.circuit_recovery_seconds:
            with _lock:
                _breakers[name]["state"] = "HALF_OPEN"
            b["state"] = "HALF_OPEN"
    b.pop("opened_at_monotonic", None)
    return b


def governed_call(name: str, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Opt-in call wrapper with timeout metadata and circuit behavior.

    It does not impose thread cancellation; providers should continue using their
    existing request timeout. This wrapper governs retries/circuit state only.
    """
    if name not in REGISTRY:
        raise KeyError(f"Unknown governed dependency: {name}")
    d = REGISTRY[name]
    state = circuit_state(name)["state"]
    if state == "OPEN":
        raise RuntimeError(f"Dependency circuit open: {name}")
    started = time.monotonic()
    attempts = d.retry_limit + 1
    last: Optional[BaseException] = None
    for _ in range(attempts):
        try:
            result = func(*args, **kwargs)
            record_observation(name, ok=True, latency_ms=(time.monotonic()-started)*1000)
            with _lock:
                _breakers[name] = {"state":"CLOSED", "failures":0, "opened_at_monotonic":None}
            return result
        except BaseException as exc:
            last = exc
    record_observation(name, ok=False, latency_ms=(time.monotonic()-started)*1000,
                       error=type(last).__name__ if last else "unknown")
    with _lock:
        b = _breaker(name)
        b["failures"] += 1
        if b["failures"] >= d.circuit_failure_threshold:
            b["state"] = "OPEN"; b["opened_at_monotonic"] = time.monotonic()
    assert last is not None
    raise last


def _status_for(name: str, env: Mapping[str, str]) -> Dict[str, Any]:
    d = REGISTRY[name]
    obs = dict(_observations.get(name, {}))
    configured = _configured(d.credential_variables, env)
    circuit = circuit_state(name)
    if circuit["state"] == "OPEN":
        state = "UNAVAILABLE"
    elif obs and not obs.get("ok"):
        state = "DEGRADED"
    elif obs.get("ok"):
        state = "HEALTHY"
    elif configured:
        state = "CONFIGURED"
    else:
        state = "NOT_CONFIGURED"
    return {
        **asdict(d), "credential_variables": list(d.credential_variables),
        "configured": configured, "state": state, "timeout_seconds": _timeout(d, env),
        "circuit": circuit, "last_observation": obs or None,
        "secret_values_exposed": False,
    }


def diagnostics(env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    e = os.environ if env is None else env
    services = [_status_for(n, e) for n in REGISTRY]
    blocked = [s["name"] for s in services if s["criticality"] in ("CRITICAL", "SAFETY_CRITICAL") and s["state"] == "UNAVAILABLE"]
    degraded = [s["name"] for s in services if s["state"] in ("DEGRADED", "NOT_CONFIGURED")]
    state = "BLOCKED" if blocked else ("WARNING" if degraded else "PASS")
    return {
        "ok": not blocked, "state": state, "version": APP_VERSION,
        "evaluated_at": _now(), "services": services,
        "blocking_dependencies": blocked, "degraded_dependencies": degraded,
        "summary": {
            "total": len(services), "healthy": sum(s["state"] == "HEALTHY" for s in services),
            "configured": sum(s["configured"] for s in services),
            "degraded": len(degraded), "blocked": len(blocked),
            "open_circuits": sum(s["circuit"]["state"] == "OPEN" for s in services),
        },
        "guardrails": {"read_only": True, "broker_mutation": False, "changes_trade_decisions": False,
                       "secret_values_returned": False},
    }


def status(env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    d = diagnostics(env)
    return {"ok": d["ok"], "state": d["state"], "version": d["version"],
            **d["summary"], "evaluated_at": d["evaluated_at"]}


def inventory() -> Dict[str, Any]:
    return {"ok": True, "version": APP_VERSION, "dependencies": [asdict(REGISTRY[n]) for n in REGISTRY],
            "count": len(REGISTRY), "evaluated_at": _now()}


def reset_runtime_state() -> None:
    with _lock:
        _observations.clear(); _breakers.clear()
