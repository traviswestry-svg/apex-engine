"""APEX persistent SQLite path + one-time legacy migration helpers.

Defaults durable evidence databases to Render's mounted /data disk when it is
available. Explicit environment variables remain authoritative.  Migration is
best-effort and never overwrites an existing durable database.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable, Optional

VERSION = "50.7.2.1_PERSISTENT_EVIDENCE_STORE"


def _writable_data_dir() -> Optional[Path]:
    p = Path("/data")
    try:
        if p.is_dir() and os.access(str(p), os.W_OK):
            return p
    except OSError:
        pass
    return None


def _legacy_project_path(filename: str) -> Path:
    return Path(__file__).resolve().parents[1] / filename


def _sqlite_backup(source: Path, target: Path) -> bool:
    """Copy a live SQLite DB consistently. Never replaces a target DB."""
    if not source.exists() or target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".migrating")
    try:
        if tmp.exists():
            tmp.unlink()
        src_uri = source.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(src_uri, uri=True, timeout=5) as src, sqlite3.connect(tmp, timeout=10) as dst:
            src.backup(dst)
        os.replace(tmp, target)
        return True
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return False


def persistent_sqlite_path(env_name: str, filename: str, *, migrate_legacy: bool = True,
                           additional_legacy_paths: Iterable[str | Path] = ()) -> str:
    """Resolve a DB path with /data as the production default.

    Explicit env configuration is honored exactly. When no env override exists,
    the first deployment using this helper attempts a SQLite-safe backup from the
    old repository-local default into /data before opening the durable store.
    """
    explicit = os.getenv(env_name)
    if explicit:
        return str(Path(explicit).expanduser())

    data = _writable_data_dir()
    if data is None:
        return str(_legacy_project_path(filename))

    target = data / filename
    if migrate_legacy and not target.exists():
        candidates = [_legacy_project_path(filename)]
        candidates.extend(Path(p).expanduser() for p in additional_legacy_paths)
        for source in candidates:
            try:
                if source.resolve() == target.resolve():
                    continue
            except OSError:
                pass
            if _sqlite_backup(source, target):
                break
    return str(target)
