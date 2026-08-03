"""APEX 65.7.3 — production scanner subprocess supervisor.

Render can launch APEX either through ``start_render.sh`` (preferred) or through
an overridden direct Gunicorn command.  A direct Gunicorn launch historically
left the web application healthy while ``scanner_worker.py`` never existed.

This module gives the WSGI boundary a fail-safe: when the scanner is *not*
explicitly managed by the shell launcher, one Gunicorn process owns a small
supervisor that starts ``scanner_worker.py`` as a separate process and restarts
it if it exits.  Scanner/HLCE ownership remains in the scanner process; the web
process never runs the scanner loop or HLCE collector itself.
"""
from __future__ import annotations

import atexit
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Dict, Optional

from .operational_runtime import persistent_path, read_scanner_heartbeat

VERSION = "65.7.3_SCANNER_STARTUP_HEARTBEAT"
_TRUE = {"1", "true", "yes", "on"}
_LOCK = threading.RLock()
_PROCESS: Optional[subprocess.Popen] = None
_WATCHDOG: Optional[threading.Thread] = None
_STOP = threading.Event()
_SUPERVISOR_LEASE_HANDLE = None
_RUNTIME: Dict[str, Any] = {
    "enabled": True,
    "managed_externally": False,
    "owner": False,
    "launches": 0,
    "last_error": None,
    "child_pid": None,
}


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in _TRUE


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _heartbeat_fresh(max_age_seconds: Optional[float] = None) -> bool:
    hb = read_scanner_heartbeat()
    if not hb.get("available"):
        return False
    limit = float(max_age_seconds or os.getenv("APEX_SCANNER_HEARTBEAT_STALE_SECONDS", "45"))
    try:
        return float(hb.get("age_seconds") or 1e9) <= limit and not bool(hb.get("stopped"))
    except (TypeError, ValueError):
        return False


def _acquire_supervisor_lease() -> bool:
    """Allow only one WSGI worker to own subprocess supervision.

    This is separate from APEX's scanner-process lease.  The scanner process
    still takes the canonical scanner lease before importing the large app.
    """
    global _SUPERVISOR_LEASE_HANDLE
    if _SUPERVISOR_LEASE_HANDLE is not None:
        return True
    try:
        import fcntl  # Linux/Render only; guarded for local portability.
        path = Path(persistent_path("apex_scanner_supervisor.lock", "APEX_SCANNER_SUPERVISOR_LEASE_PATH"))
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a+", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        _SUPERVISOR_LEASE_HANDLE = handle
        return True
    except Exception:
        return False


def _launch_locked() -> Optional[subprocess.Popen]:
    global _PROCESS
    if _PROCESS is not None and _PROCESS.poll() is None:
        return _PROCESS

    env = dict(os.environ)
    env["RUN_SCANNER_ON_IMPORT"] = "false"
    env["APEX_SCANNER_BOOTSTRAP_SOURCE"] = "wsgi_supervisor"
    # The child is the scanner owner.  This flag applies only to Gunicorn's
    # decision about whether *it* should launch a child; scanner_worker ignores it.
    cmd = [sys.executable, "scanner_worker.py"]
    try:
        _PROCESS = subprocess.Popen(cmd, cwd=str(_repo_root()), env=env)
        _RUNTIME.update({
            "launches": int(_RUNTIME.get("launches") or 0) + 1,
            "last_error": None,
            "child_pid": _PROCESS.pid,
        })
        print(f"APEX 65.7.3: WSGI supervisor launched scanner_worker.py pid={_PROCESS.pid}", flush=True)
        return _PROCESS
    except Exception as exc:
        _RUNTIME.update({"last_error": f"{type(exc).__name__}: {exc}", "child_pid": None})
        print(f"APEX 65.7.3: scanner subprocess launch failed: {exc}", flush=True)
        return None


def _watchdog_loop() -> None:
    interval = max(5.0, float(os.getenv("APEX_SCANNER_SUPERVISOR_SECONDS", "10")))
    while not _STOP.wait(interval):
        with _LOCK:
            proc = _PROCESS
            if proc is not None and proc.poll() is None:
                continue
            # If another valid scanner owner is publishing a heartbeat, do not
            # compete with it.  This also makes rolling restarts safe.
            if _heartbeat_fresh():
                continue
            _launch_locked()


def ensure_scanner_process() -> Dict[str, Any]:
    """Ensure a separate scanner process exists for this deployment.

    Preferred shell launchers set ``APEX_SCANNER_MANAGED_EXTERNALLY=true`` and
    therefore skip this fallback.  Direct Gunicorn launches use the fallback.
    """
    global _WATCHDOG
    explicit = os.getenv("APEX_WSGI_ENSURE_SCANNER")
    production_default = bool(
        _truthy("RENDER")
        or os.getenv("RENDER_SERVICE_ID")
        or str(os.getenv("APEX_ENVIRONMENT", "")).lower() == "production"
    )
    enabled = _truthy("APEX_WSGI_ENSURE_SCANNER") if explicit is not None else production_default
    if _truthy("DISABLE_BACKGROUND_SCANNER") or not enabled:
        _RUNTIME.update({"enabled": False})
        return dict(_RUNTIME)
    _RUNTIME.update({"enabled": True})

    if _truthy("APEX_SCANNER_MANAGED_EXTERNALLY"):
        _RUNTIME.update({"managed_externally": True, "owner": False})
        return dict(_RUNTIME)

    with _LOCK:
        if not _acquire_supervisor_lease():
            _RUNTIME.update({"owner": False})
            return dict(_RUNTIME)
        _RUNTIME.update({"owner": True, "managed_externally": False})

        # A fresh scanner heartbeat may belong to a sibling/old worker during a
        # rolling restart.  Respect it rather than launching a competitor.
        if not _heartbeat_fresh():
            _launch_locked()

        if _WATCHDOG is None or not _WATCHDOG.is_alive():
            _WATCHDOG = threading.Thread(
                target=_watchdog_loop,
                name="apex-scanner-process-supervisor",
                daemon=True,
            )
            _WATCHDOG.start()
        return dict(_RUNTIME)


def supervisor_status() -> Dict[str, Any]:
    with _LOCK:
        proc = _PROCESS
        payload = dict(_RUNTIME)
        payload.update({
            "version": VERSION,
            "child_alive": bool(proc is not None and proc.poll() is None),
            "heartbeat_fresh": _heartbeat_fresh(),
        })
        return payload


def _shutdown() -> None:
    _STOP.set()
    with _LOCK:
        proc = _PROCESS
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=8)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


atexit.register(_shutdown)
