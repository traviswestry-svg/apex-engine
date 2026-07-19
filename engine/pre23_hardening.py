"""APEX 22.5 — pre-23 hardening and consolidation utilities.

Read-only diagnostics plus a process-scoped scanner lease. No trading decisions
or broker mutations are performed here.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

VERSION = "15.5.0_PRE_23_HARDENING"
_CRITICAL_ROUTES = (
    "/health", "/apex_os", "/api/configuration/status",
    "/api/dependencies/status", "/api/institutional-decision/status",
    "/api/institutional-workspace/status", "/api/mission-control-v2/status",
    "/api/market-memory/status",
)
_LOCK = threading.RLock()
_SCANNER_LEASE_HANDLE = None


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def immutable_snapshot(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a deep-copied, content-addressed point-in-time snapshot."""
    body = copy.deepcopy(dict(payload or {}))
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "snapshot_id": hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24],
        "generated_at": utcnow(),
        "payload": body,
        "immutable": True,
    }


def route_assurance(app) -> Dict[str, Any]:
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    missing = [route for route in _CRITICAL_ROUTES if route not in rules]
    return {
        "ok": not missing,
        "state": "PASS" if not missing else "BLOCKING",
        "version": VERSION,
        "registered_routes": len(rules),
        "critical_routes": list(_CRITICAL_ROUTES),
        "missing_critical_routes": missing,
        "evaluated_at": utcnow(),
    }


def persistence_inventory(root: Optional[str] = None) -> Dict[str, Any]:
    base = pathlib.Path(root or pathlib.Path(__file__).resolve().parents[1])
    env_pattern = re.compile(r"os\.(?:getenv|environ\.get)\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]")
    sqlite_pattern = re.compile(r"(?:sqlite3\.connect\(|DB_PATH|_DB\b|\.db['\"])")
    stores = []
    for path in [base / "app.py", *(base / "engine").rglob("*.py")]:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not sqlite_pattern.search(text):
            continue
        names = sorted(set(env_pattern.findall(text)))
        db_names = [name for name in names if "DB" in name or "DATABASE" in name]
        if db_names or "sqlite3.connect" in text:
            stores.append({"file": str(path.relative_to(base)), "environment_paths": db_names})
    persistent_root = os.getenv("RENDER_DISK_PATH") or os.getenv("APEX_PERSISTENT_DISK_PATH")
    warnings = []
    if not persistent_root:
        warnings.append("No Render persistent-disk root is declared; SQLite stores may be ephemeral.")
    return {
        "ok": True,
        "state": "WARNING" if warnings else "PASS",
        "version": VERSION,
        "stores": stores,
        "store_count": len(stores),
        "persistent_disk_root": persistent_root,
        "warnings": warnings,
        "evaluated_at": utcnow(),
    }


def acquire_scanner_lease(path: Optional[str] = None) -> Dict[str, Any]:
    """Acquire a non-blocking process lease so one worker owns the scanner."""
    global _SCANNER_LEASE_HANDLE
    lease_path = path or os.getenv("APEX_SCANNER_LEASE_PATH", "/tmp/apex_scanner.lock")
    with _LOCK:
        if _SCANNER_LEASE_HANDLE is not None:
            return {"acquired": True, "path": lease_path, "owner_pid": os.getpid(), "reused": True}
        try:
            import fcntl
            handle = open(lease_path, "a+", encoding="utf-8")
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            handle.seek(0); handle.truncate(); handle.write(str(os.getpid())); handle.flush()
            _SCANNER_LEASE_HANDLE = handle
            return {"acquired": True, "path": lease_path, "owner_pid": os.getpid(), "reused": False}
        except (OSError, ImportError) as exc:
            return {"acquired": False, "path": lease_path, "owner_pid": None, "reason": type(exc).__name__}


def hardening_status(app=None) -> Dict[str, Any]:
    route = route_assurance(app) if app is not None else None
    persistence = persistence_inventory()
    states = [x.get("state") for x in (route, persistence) if x]
    state = "BLOCKING" if "BLOCKING" in states else "WARNING" if "WARNING" in states else "PASS"
    return {
        "ok": state != "BLOCKING", "state": state, "version": VERSION,
        "route_assurance": route, "persistence": persistence,
        "guardrails": {"read_only": True, "changes_trade_decisions": False, "broker_mutation": False},
        "evaluated_at": utcnow(),
    }
