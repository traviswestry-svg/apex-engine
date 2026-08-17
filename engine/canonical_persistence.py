"""APEX 67.0.0 — Canonical SQLite persistence layer.

One connection policy for APEX-owned SQLite stores. It standardizes timeout,
busy handling, WAL/synchronous mode, foreign-key enforcement, row access,
transaction boundaries, and lightweight diagnostics while preserving existing
schemas and database paths.

It does not migrate schemas, move files, or change execution authority.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .db_resilience import ensure_healthy_db

VERSION = "67.0.0"
SCHEMA_VERSION = "apex.canonical_persistence.v1"

DEFAULT_TIMEOUT_SECONDS = float(os.getenv("APEX_SQLITE_TIMEOUT_SECONDS", "15"))
DEFAULT_BUSY_TIMEOUT_MS = int(os.getenv("APEX_SQLITE_BUSY_TIMEOUT_MS", "15000"))
DEFAULT_SYNCHRONOUS = os.getenv("APEX_SQLITE_SYNCHRONOUS", "NORMAL").strip().upper() or "NORMAL"
ALLOWED_SYNCHRONOUS = {"OFF", "NORMAL", "FULL", "EXTRA"}


def _resolved(path: str | Path) -> str:
    return str(Path(path).expanduser()) if str(path) not in {":memory:", ""} else str(path)


def connect(
    path: str | Path,
    *,
    read_only: bool = False,
    timeout: float | None = None,
    row_factory: bool = True,
    foreign_keys: bool = True,
    wal: bool = True,
    heal: bool = True,
) -> sqlite3.Connection:
    """Open a SQLite database using APEX's canonical connection policy."""
    resolved = _resolved(path)
    if not resolved:
        raise ValueError("SQLite path must not be empty")

    if resolved != ":memory:" and not read_only:
        parent = os.path.dirname(resolved)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if heal:
            ensure_healthy_db(resolved)

    effective_timeout = DEFAULT_TIMEOUT_SECONDS if timeout is None else float(timeout)
    if read_only and resolved != ":memory:":
        uri = f"file:{Path(resolved).resolve().as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=effective_timeout)
    else:
        conn = sqlite3.connect(resolved, timeout=effective_timeout)

    if row_factory:
        conn.row_factory = sqlite3.Row

    conn.execute(f"PRAGMA busy_timeout={max(0, DEFAULT_BUSY_TIMEOUT_MS)}")
    if foreign_keys:
        conn.execute("PRAGMA foreign_keys=ON")

    # WAL is a write-side property. Never attempt to mutate journaling from
    # read-only consumers or in-memory databases.
    if wal and not read_only and resolved != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
        sync = DEFAULT_SYNCHRONOUS if DEFAULT_SYNCHRONOUS in ALLOWED_SYNCHRONOUS else "NORMAL"
        conn.execute(f"PRAGMA synchronous={sync}")

    return conn


@contextmanager
def connection(path: str | Path, **kwargs: Any) -> Iterator[sqlite3.Connection]:
    """Context manager that always closes the connection.

    SQLite's native connection context commits/rolls back but does not close;
    this wrapper makes lifecycle explicit and consistent across APEX.
    """
    conn = connect(path, **kwargs)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(path: str | Path, **kwargs: Any) -> Iterator[sqlite3.Connection]:
    """Atomic write transaction with rollback on error and guaranteed close."""
    kwargs.pop("read_only", None)
    conn = connect(path, read_only=False, **kwargs)
    try:
        conn.execute("BEGIN")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def diagnostics(path: str | Path) -> dict[str, Any]:
    """Return non-mutating persistence policy diagnostics for one DB."""
    resolved = _resolved(path)
    exists = resolved == ":memory:" or os.path.exists(resolved)
    result: dict[str, Any] = {
        "ok": True,
        "path": resolved,
        "exists": exists,
        "engine_version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "policy": {
            "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
            "busy_timeout_ms": DEFAULT_BUSY_TIMEOUT_MS,
            "journal_mode_target": "WAL",
            "synchronous_target": DEFAULT_SYNCHRONOUS,
            "foreign_keys": True,
        },
    }
    if not exists or resolved == ":memory:":
        result["journal_mode"] = None
        result["foreign_keys"] = None
        return result
    try:
        with connection(resolved, read_only=True, wal=False, heal=False) as conn:
            result["journal_mode"] = conn.execute("PRAGMA journal_mode").fetchone()[0]
            result["foreign_keys"] = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
            result["integrity"] = conn.execute("PRAGMA quick_check").fetchone()[0]
    except Exception as exc:
        result.update({"ok": False, "error": type(exc).__name__, "detail": str(exc)})
    return result
