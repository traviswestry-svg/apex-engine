"""APEX 24.2.1 operational hardening helpers.

Centralizes persistent paths, SQLite connection policy, storage telemetry, and
scanner-process heartbeat without changing trade-decision logic.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import shutil
import sqlite3
from typing import Any, Dict, Optional

VERSION = "24.2.1_PRODUCTION_HARDENING"


def persistent_root() -> pathlib.Path:
    raw = os.getenv("APEX_PERSISTENT_DISK_PATH") or os.getenv("RENDER_DISK_PATH") or "/data"
    root = pathlib.Path(raw)
    if not root.exists() or not os.access(root, os.W_OK):
        root = pathlib.Path(os.getenv("APEX_LOCAL_DATA_DIR", "."))
    return root.resolve()


def persistent_path(filename: str, env_name: Optional[str] = None) -> str:
    configured = (os.getenv(env_name, "") if env_name else "").strip()
    if configured:
        return configured
    root = persistent_root()
    root.mkdir(parents=True, exist_ok=True)
    return str(root / filename)


def connect_sqlite(
    path: str,
    *,
    timeout: Optional[float] = None,
    row_factory: bool = True,
    foreign_keys: bool = True,
    wal: bool = True,
) -> sqlite3.Connection:
    """Return an APEX-standard SQLite connection.

    The function is additive; existing modules may migrate to it incrementally.
    """
    db_path = pathlib.Path(path)
    if db_path.parent and str(db_path.parent) not in ("", "."):
        db_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_timeout = float(timeout if timeout is not None else os.getenv("APEX_SQLITE_TIMEOUT_SECONDS", "15"))
    conn = sqlite3.connect(str(db_path), timeout=resolved_timeout)
    if row_factory:
        conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={int(resolved_timeout * 1000)}")
    if foreign_keys:
        conn.execute("PRAGMA foreign_keys=ON")
    if wal:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.DatabaseError:
            pass
    return conn


def storage_status() -> Dict[str, Any]:
    root = persistent_root()
    root.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(root)
    files = []
    total_db_bytes = 0
    for path in sorted(root.glob("*.db*")):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        total_db_bytes += size
        files.append({"name": path.name, "bytes": size})
    free_pct = (usage.free / usage.total * 100.0) if usage.total else 0.0
    warn_pct = float(os.getenv("APEX_DISK_WARN_FREE_PCT", "15"))
    critical_pct = float(os.getenv("APEX_DISK_CRITICAL_FREE_PCT", "7"))
    state = "CRITICAL" if free_pct <= critical_pct else "WARNING" if free_pct <= warn_pct else "PASS"
    return {
        "ok": state != "CRITICAL",
        "state": state,
        "root": str(root),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "free_pct": round(free_pct, 2),
        "database_bytes": total_db_bytes,
        "database_files": files,
        "evaluated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def scanner_heartbeat_path() -> pathlib.Path:
    return pathlib.Path(persistent_path("scanner_heartbeat.json", "APEX_SCANNER_HEARTBEAT_PATH"))


def write_scanner_heartbeat(payload: Optional[Dict[str, Any]] = None) -> None:
    body = {
        "pid": os.getpid(),
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "version": VERSION,
    }
    if payload:
        body.update(payload)
    path = scanner_heartbeat_path()
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def read_scanner_heartbeat() -> Dict[str, Any]:
    path = scanner_heartbeat_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        updated = dt.datetime.fromisoformat(str(payload.get("updated_at", "")).replace("Z", "+00:00"))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=dt.timezone.utc)
        age = max(0.0, (dt.datetime.now(dt.timezone.utc) - updated).total_seconds())
        payload.update({"available": True, "age_seconds": round(age, 2), "path": str(path)})
        return payload
    except Exception as exc:
        return {"available": False, "path": str(path), "error": type(exc).__name__}
