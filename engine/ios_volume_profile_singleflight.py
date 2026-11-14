"""Bounded, process-local Institutional OS volume-profile fetch.

A Future timeout does not stop an already-running provider. A new executor per
compose therefore permits overlapping stragglers. This module reserves one
non-queueing slot until the *actual* provider call returns, even after caller
has timed out. It never changes the provider implementation or trading logic.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, Callable, Dict, Tuple

_SLOT = threading.BoundedSemaphore(1)
_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="apex-ios-vp")
_LOCK = threading.Lock()
_METRICS = {"attempts": 0, "completed": 0, "timed_out": 0, "busy_skips": 0, "provider_errors": 0}


def _run_and_release(provider: Callable[..., Any], kwargs: Dict[str, Any]) -> Any:
    try:
        return provider(**kwargs)
    finally:
        _SLOT.release()


def fetch(provider: Callable[..., Any], *, timeout: float, **kwargs: Any) -> Tuple[Any, str, float]:
    """Return (value, status, elapsed_ms).

    status: COMPLETED, TIMED_OUT, BUSY, FAILED. The BUSY result is an empty
    bundle, as for the previous timeout path. A running provider is never
    cancelled or duplicated. The slot is held until the task really exits.
    """
    started = time.monotonic()
    with _LOCK:
        _METRICS["attempts"] += 1
    if not _SLOT.acquire(blocking=False):
        with _LOCK:
            _METRICS["busy_skips"] += 1
        return {}, "BUSY", round((time.monotonic() - started) * 1000, 1)
    try:
        future = _POOL.submit(_run_and_release, provider, dict(kwargs))
    except BaseException:
        _SLOT.release()
        raise
    try:
        value = future.result(timeout=timeout)
        with _LOCK:
            _METRICS["completed"] += 1
        return value, "COMPLETED", round((time.monotonic() - started) * 1000, 1)
    except FutureTimeout:
        # Do not cancel a queued/running Future: the provider task owns the slot
        # and must release it after returning. This prevents overlap on retries.
        with _LOCK:
            _METRICS["timed_out"] += 1
        return {}, "TIMED_OUT", round((time.monotonic() - started) * 1000, 1)
    except Exception:
        with _LOCK:
            _METRICS["provider_errors"] += 1
        return {}, "FAILED", round((time.monotonic() - started) * 1000, 1)


def snapshot() -> Dict[str, Any]:
    """Constant-size, read-only operational counters; no payload retention."""
    with _LOCK:
        counts = dict(_METRICS)
    return {"schema": "apex.ios_volume_profile_singleflight.v1",
            "process_local": True, "max_active_provider_calls": 1,
            "read_only": True, "decision_authority": False,
            "execution_authority": False, **counts}
