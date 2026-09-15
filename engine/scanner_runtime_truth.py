"""APEX 69.10.12 cross-process scanner lifecycle and completion truth.

The dedicated ``scanner_worker.py`` process owns production scanning.  Flask /
Gunicorn process-local scanner flags are not authoritative when a fresh durable
scanner heartbeat exists.  This resolver therefore treats any fresh heartbeat
as the canonical process-boundary authority, including STARTING/NOT_STARTED
states, rather than requiring ``scanner_started`` to already be true before the
heartbeat can become authoritative.

Observational only: no decision, calibration, broker, or execution authority.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping

VERSION = "69.10.12"


def resolve_scanner_runtime(*, local_started: bool, local_thread_alive: bool,
                            heartbeat: Mapping[str, Any] | None,
                            stale_after_seconds: float = 45.0) -> Dict[str, Any]:
    hb = dict(heartbeat or {})
    try:
        fresh = (
            bool(hb.get("available"))
            and float(hb.get("age_seconds") if hb.get("age_seconds") is not None else 1e9)
                <= float(stale_after_seconds)
            and not bool(hb.get("stopped"))
        )
    except (TypeError, ValueError):
        fresh = False

    process_started = bool(fresh and hb.get("scanner_started"))
    process_thread_alive = bool(fresh and hb.get("thread_alive"))

    # 69.10.12: freshness establishes process authority.  A fresh STARTING
    # heartbeat is still authoritative evidence that the scanner owner has not
    # started its scan thread yet.  Never merge a web-local True into a fresh
    # scanner-process False; that recreates the cross-process truth ambiguity.
    if fresh:
        effective_started = process_started
        effective_thread_alive = process_thread_alive
        source = "SCANNER_PROCESS_HEARTBEAT"
        authority = "SCANNER_PROCESS"
    else:
        effective_started = bool(local_started)
        effective_thread_alive = bool(local_thread_alive)
        source = "WEB_PROCESS_LOCAL_STATE"
        authority = "WEB_PROCESS_FALLBACK"

    completion = dict(hb.get("scan_completion_runtime") or {}) if fresh else {}
    process_completed_at = completion.get("last_completed_at") or (hb.get("last_scan_at") if fresh else None)
    process_scan_duration = completion.get("last_duration_seconds")
    process_scan_in_progress = bool(completion.get("scan_in_progress")) if fresh else False
    process_scan_started_at = completion.get("scan_started_at") if fresh else None

    return {
        "version": VERSION,
        "heartbeat": hb,
        "heartbeat_fresh": fresh,
        "effective_started": effective_started,
        "effective_thread_alive": effective_thread_alive,
        "process_last_scan_at": process_completed_at,
        "process_last_scan_duration_seconds": process_scan_duration,
        "process_scan_completion": completion,
        "process_scan_in_progress": process_scan_in_progress,
        "process_scan_started_at": process_scan_started_at,
        "process_heartbeat_at": hb.get("updated_at") if fresh else None,
        "process_phase": hb.get("phase") if fresh else None,
        "process_pid": hb.get("pid") if fresh else None,
        "source": source,
        "authority": authority,
        "execution_authority": False,
        "behavioral_authority": False,
    }
