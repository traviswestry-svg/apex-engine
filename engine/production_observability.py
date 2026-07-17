"""APEX 10 Sprint 8 production observability and integration-health contracts.

The module is deliberately dependency-light and safe to use from request paths.
It records bounded in-memory latency/error samples and exposes honest health
summaries. It never changes trading decisions.
"""
from __future__ import annotations

import datetime as dt
import math
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from copy import deepcopy
from typing import Any, Deque, Dict, Iterator, Optional

VERSION = "10.1.0_PRODUCTION_OBSERVABILITY"
_MAX_SAMPLES = 512
_lock = threading.RLock()
_latency_ms: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=_MAX_SAMPLES))
_errors: Dict[str, int] = defaultdict(int)
_last_error: Dict[str, Dict[str, Any]] = {}
_counters: Dict[str, int] = defaultdict(int)
_started = time.monotonic()


def reset_metrics() -> None:
    global _started
    with _lock:
        _latency_ms.clear(); _errors.clear(); _last_error.clear(); _counters.clear()
        _started = time.monotonic()


def record_latency(component: str, elapsed_ms: float) -> None:
    with _lock:
        _latency_ms[str(component)].append(max(0.0, float(elapsed_ms)))
        _counters[f"{component}.calls"] += 1


def record_error(component: str, exc: BaseException) -> None:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with _lock:
        _errors[str(component)] += 1
        _last_error[str(component)] = {
            "at": now,
            "type": type(exc).__name__,
            "message": str(exc)[:500],
        }


def increment(name: str, amount: int = 1) -> None:
    with _lock:
        _counters[str(name)] += int(amount)


@contextmanager
def timed(component: str) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    except Exception as exc:
        record_error(component, exc)
        raise
    finally:
        record_latency(component, (time.perf_counter() - start) * 1000.0)


def _percentile(values: list[float], percentile: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return round(ordered[idx], 3)


def metrics_snapshot() -> Dict[str, Any]:
    with _lock:
        components: Dict[str, Any] = {}
        names = sorted(set(_latency_ms) | set(_errors))
        for name in names:
            values = list(_latency_ms.get(name, ()))
            components[name] = {
                "samples": len(values),
                "p50_ms": _percentile(values, .50),
                "p95_ms": _percentile(values, .95),
                "max_ms": round(max(values), 3) if values else None,
                "errors": int(_errors.get(name, 0)),
                "last_error": deepcopy(_last_error.get(name)),
            }
        return {
            "version": VERSION,
            "uptime_seconds": round(time.monotonic() - _started, 3),
            "components": components,
            "counters": dict(sorted(_counters.items())),
        }


def integration_health(*, capabilities: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
    caps = {str(k): bool(v) for k, v in (capabilities or {}).items()}
    missing = sorted(k for k, v in caps.items() if not v)
    metrics = metrics_snapshot()
    total_errors = sum(int(v.get("errors") or 0) for v in metrics["components"].values())
    status = "DEGRADED" if missing or total_errors else "HEALTHY"
    return {
        "status": status,
        "ready": not missing,
        "capabilities": caps,
        "missing_capabilities": missing,
        "total_observed_errors": total_errors,
        "metrics": metrics,
        "guardrails": {
            "read_only": True,
            "changes_trade_decisions": False,
            "bounded_memory": True,
            "sample_limit_per_component": _MAX_SAMPLES,
        },
    }
