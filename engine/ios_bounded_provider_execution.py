"""Bounded, per-web-process Institutional OS provider execution.

Research/infrastructure safety only. No trading decision or execution authority.
Six in-flight provider calls maximum, with NO pending-work backlog. A timeout
never frees the reservation until the underlying Future is actually done.
No fetched payload is retained in module globals; responses live with caller.
"""
from concurrent.futures import ThreadPoolExecutor, TimeoutError, wait
from threading import BoundedSemaphore, Lock
import time

_MAX_ACTIVE = 6
_POOL = ThreadPoolExecutor(max_workers=_MAX_ACTIVE, thread_name_prefix="apex-os-fetch")
_CAPACITY = BoundedSemaphore(_MAX_ACTIVE)
_LOCK = Lock()
_ACTIVE_KEYS = set()
_COUNTS = {"attempts": 0, "submitted": 0, "completed": 0,
           "timed_out": 0, "busy_skips": 0, "provider_errors": 0,
           "active": 0, "peak_active": 0}


def _claim(key):
    # Lock encloses both duplicate check and semaphore admission. Never queue
    # work while slots are occupied by slow (even previously timed-out) calls.
    with _LOCK:
        _COUNTS["attempts"] += 1
        if key in _ACTIVE_KEYS or not _CAPACITY.acquire(blocking=False):
            _COUNTS["busy_skips"] += 1
            return False
        _ACTIVE_KEYS.add(key)
        _COUNTS["submitted"] += 1
        _COUNTS["active"] += 1
        _COUNTS["peak_active"] = max(_COUNTS["peak_active"], _COUNTS["active"])
        return True


def _release(key, future):
    # Future callback fires for normal completion, error, and cancellation.
    # No result/payload is accessed or retained here.
    with _LOCK:
        if key not in _ACTIVE_KEYS:
            return
        _ACTIVE_KEYS.remove(key)
        _COUNTS["active"] -= 1
        if not future.cancelled():
            _COUNTS["completed"] += 1
            if future.exception() is not None:
                _COUNTS["provider_errors"] += 1
        _CAPACITY.release()


def fetch_many(specs, timeout):
    """Run (key, callable, args, default) specs with ONE shared deadline.

    Output: (results_by_key, degraded_keys, statuses_by_key).
    Duplicate keys within a batch are rejected to prevent silent clobbering.
    Busy keys fail closed to the provided defaults, with no new work launched.
    This is not a cache; all outputs are caller-owned and dropped afterwards.
    """
    specs = list(specs)
    keys = [s[0] for s in specs]
    if len(keys) != len(set(keys)):
        raise ValueError("IOS_PROVIDER_DUPLICATE_KEY_IN_BATCH")
    timeout = max(0.0, float(timeout))
    deadline = time.monotonic() + timeout
    futures = {}
    values = {}
    status = {}
    defaults = {key: default for key, _, _, default in specs}
    for key, provider, args, default in specs:
        if not _claim(key):
            values[key] = default
            status[key] = "BUSY_SKIPPED"
            continue
        try:
            future = _POOL.submit(provider, *args)
        except Exception:
            # Submission failure has no future; manually release the claim.
            with _LOCK:
                _ACTIVE_KEYS.remove(key)
                _COUNTS["active"] -= 1
                _COUNTS["provider_errors"] += 1
                _CAPACITY.release()
            values[key] = default
            status[key] = "SUBMIT_FAILED"
            continue
        future.add_done_callback(lambda completed, identity=key: _release(identity, completed))
        futures[key] = future
    if futures:
        wait(tuple(futures.values()), timeout=max(0.0, deadline - time.monotonic()))
    for key, future in futures.items():
        if future.done():
            try:
                values[key] = future.result()
                status[key] = "COMPLETED"
            except Exception:
                values[key] = defaults[key]
                status[key] = "PROVIDER_ERROR"
        else:
            future.cancel()  # Running provider cannot be stopped; slot stays held.
            values[key] = defaults[key]
            status[key] = "TIMED_OUT"
            with _LOCK:
                _COUNTS["timed_out"] += 1
    degraded = [key for key in keys if status[key] != "COMPLETED"]
    return values, degraded, status


def snapshot():
    with _LOCK:
        counters = dict(_COUNTS)
    return {"schema": "apex.ios_bounded_provider_execution.v1",
            "read_only": True, "execution_authority": False,
            "decision_authority": False, "changes_trade_decisions": False,
            "process_local": True, "maximum_active_calls": _MAX_ACTIVE,
            "pending_queue_limit": 0, "retained_provider_payloads": 0,
            **counters}
