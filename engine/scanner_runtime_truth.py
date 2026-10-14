"""APEX cross-process scanner lifecycle truth; observability-only extension."""
from __future__ import annotations
import math
from typing import Any, Dict, Mapping

VERSION = "69.10.38-runtime-observability-candidate"


def resolve_scanner_runtime(*, local_started: bool, local_thread_alive: bool,
                            heartbeat: Mapping[str, Any] | None,
                            stale_after_seconds: float = 45.0) -> Dict[str, Any]:
    hb = dict(heartbeat or {})
    available = bool(hb.get("available"))
    try:
        age = float(hb.get("age_seconds"))
        age_valid = math.isfinite(age) and age >= 0
    except (TypeError, ValueError):
        age, age_valid = None, False
    try:
        threshold = float(stale_after_seconds)
        threshold_valid = math.isfinite(threshold) and threshold >= 0
    except (TypeError, ValueError):
        threshold, threshold_valid = None, False
    stopped = bool(hb.get("stopped"))
    fresh = available and age_valid and threshold_valid and age <= threshold and not stopped
    if not available:
        reason = "HEARTBEAT_UNAVAILABLE"
    elif not age_valid:
        reason = "INVALID_HEARTBEAT_AGE"
    elif not threshold_valid:
        reason = "INVALID_FRESHNESS_THRESHOLD"
    elif stopped:
        reason = "SCANNER_STOPPED"
    elif age > threshold:
        reason = "HEARTBEAT_STALE"
    else:
        reason = "FRESH"
    process_started = bool(fresh and hb.get("scanner_started"))
    process_thread_alive = bool(fresh and hb.get("thread_alive"))
    effective_started = process_started if fresh else bool(local_started)
    effective_thread_alive = process_thread_alive if fresh else bool(local_thread_alive)
    completion = dict(hb.get("scan_completion_runtime") or {}) if fresh else {}
    return {
        "version": VERSION, "heartbeat": hb, "heartbeat_fresh": fresh,
        "heartbeat_reason": reason, "heartbeat_age_seconds": age if age_valid else None,
        "heartbeat_stale_after_seconds": threshold if threshold_valid else None,
        "heartbeat_error": hb.get("error"),
        "effective_started": effective_started,
        "effective_thread_alive": effective_thread_alive,
        "process_last_scan_at": completion.get("last_completed_at") or (hb.get("last_scan_at") if fresh else None),
        "process_last_scan_duration_seconds": completion.get("last_duration_seconds"),
        "process_scan_completion": completion,
        "process_scan_in_progress": bool(completion.get("scan_in_progress")) if fresh else False,
        "process_scan_started_at": completion.get("scan_started_at") if fresh else None,
        "process_heartbeat_at": hb.get("updated_at") if fresh else None,
        "process_phase": hb.get("phase") if fresh else None,
        "process_pid": hb.get("pid") if fresh else None,
        "source": "SCANNER_PROCESS_HEARTBEAT" if fresh else "WEB_PROCESS_LOCAL_STATE",
        "authority": "SCANNER_PROCESS" if fresh else "WEB_PROCESS_FALLBACK",
        "execution_authority": False, "behavioral_authority": False,
    }
