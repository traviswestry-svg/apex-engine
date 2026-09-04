"""APEX 69.10.1 cross-process scanner lifecycle truth.

Production normally owns scanning in ``scanner_worker.py`` while Flask/Gunicorn
runs in a different process.  A web-process local ``SCANNER_STARTED`` flag is
therefore not authoritative.  This module deterministically merges local state
with the durable scanner heartbeat; a fresh heartbeat may prove the scanner is
running, while a stale or missing heartbeat never does.

Observational only: no decision, calibration, broker, or execution authority.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping

VERSION = "69.10.1"


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
    effective_started = bool(local_started or process_started)
    effective_thread_alive = bool(local_thread_alive or process_thread_alive)
    source = "SCANNER_PROCESS_HEARTBEAT" if process_started else "WEB_PROCESS_LOCAL_STATE"

    return {
        "version": VERSION,
        "heartbeat": hb,
        "heartbeat_fresh": fresh,
        "effective_started": effective_started,
        "effective_thread_alive": effective_thread_alive,
        "process_last_scan_at": hb.get("last_scan_at") if fresh else None,
        "process_heartbeat_at": hb.get("updated_at") if fresh else None,
        "source": source,
        "execution_authority": False,
        "behavioral_authority": False,
    }
