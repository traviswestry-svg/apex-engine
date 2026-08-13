"""APEX DB resilience — quarantine a corrupt SQLite file before it is used.

Interrupted writes (e.g. a deploy cancelled mid-flight while the mounted disk is
being written) can leave a database file whose header is invalid. SQLite then
raises ``file is not a database`` on every open, which silently disables tracking
and the signal evaluator. This helper detects that condition cheaply and moves
the bad file aside so the application can recreate a fresh one, turning a hard
brick into a self-healing event.

It is intentionally conservative: it only quarantines a file it can prove is
unreadable, it never deletes data, and any unexpected error leaves the file
untouched (the caller's own error handling still applies).
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
from typing import Any

# Skip healing for these pseudo-paths.
_SKIP = {"", ":memory:"}


def _is_readable_sqlite(path: str) -> bool:
    """Cheaply verify the file has a valid SQLite header and is queryable.

    Uses ``PRAGMA schema_version`` (reads the header only) plus a trivial
    ``sqlite_master`` read — enough to catch the ``file is not a database``
    corruption without the cost of a full ``integrity_check`` on a large DB.
    """
    conn = None
    try:
        conn = sqlite3.connect(path, timeout=5)
        conn.execute("PRAGMA schema_version;").fetchone()
        conn.execute("SELECT name FROM sqlite_master LIMIT 1;").fetchone()
        return True
    except sqlite3.DatabaseError:
        return False
    except Exception:
        # Unknown error (permissions, locking, etc.) — do not quarantine.
        return True
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def ensure_healthy_db(path: str) -> dict[str, Any]:
    """Ensure the SQLite file at ``path`` is usable, quarantining it if not.

    Returns a small status dict. When a corrupt file is found it is renamed to
    ``<path>.corrupt-<UTC timestamp>.bak`` and ``healed`` is True; the caller's
    next connect then creates a fresh database.
    """
    if not path or path in _SKIP:
        return {"ok": True, "healed": False, "reason": "no-op path"}
    try:
        if not os.path.exists(path):
            return {"ok": True, "healed": False, "reason": "absent (will be created)"}
        if os.path.getsize(path) == 0:
            return {"ok": True, "healed": False, "reason": "empty (will be initialized)"}
        if _is_readable_sqlite(path):
            return {"ok": True, "healed": False, "reason": "healthy"}

        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
        quarantine = f"{path}.corrupt-{stamp}.bak"
        os.replace(path, quarantine)
        print(f"APEX db_resilience: quarantined corrupt DB '{path}' -> '{quarantine}'. "
              f"A fresh database will be created.", flush=True)
        return {"ok": True, "healed": True, "quarantined_to": quarantine,
                "reason": "corrupt file quarantined"}
    except Exception as exc:  # never let healing itself crash startup
        print(f"APEX db_resilience: heal check failed for '{path}' (leaving as-is): {exc}",
              flush=True)
        return {"ok": False, "healed": False, "reason": str(exc)}
