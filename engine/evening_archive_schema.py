"""Low-level APEX 49 archive schema bootstrap.

This module deliberately has no dependency on ``engine.evening_recap``.  Startup
and read-model code can therefore ensure the archive schema exists without
importing the recap service while the Flask application is still initializing.
"""
from __future__ import annotations

from .canonical_persistence import connect as canonical_connect

import os
import sqlite3


def init_evening_archive_db(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    with canonical_connect(db_path, timeout=10) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS apex49_morning_snapshots(
          session_date TEXT PRIMARY KEY,
          generated_at TEXT NOT NULL,
          ticker TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          version TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS apex49_morning_revisions(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_date TEXT NOT NULL,
          generated_at TEXT NOT NULL,
          ticker TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          version TEXT NOT NULL,
          is_official INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS apex49_evening_recaps(
          session_date TEXT PRIMARY KEY,
          generated_at TEXT NOT NULL,
          ticker TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          score REAL,
          grade TEXT NOT NULL,
          version TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_apex49_recap_generated ON apex49_evening_recaps(generated_at);
        CREATE INDEX IF NOT EXISTS idx_apex49_morning_revision_date ON apex49_morning_revisions(session_date, generated_at);
        """)
        # 69.10.28 additive migration. Existing historical rows remain legacy/unverified;
        # they are never retroactively assigned canonical identity.
        cols = {r[1] for r in c.execute("PRAGMA table_info(apex49_morning_snapshots)").fetchall()}
        for name, decl in (
            ("forecast_id", "TEXT"),
            ("snapshot_hash", "TEXT"),
            ("canonical_components_json", "TEXT"),
        ):
            if name not in cols:
                c.execute(f"ALTER TABLE apex49_morning_snapshots ADD COLUMN {name} {decl}")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_apex49_forecast_id ON apex49_morning_snapshots(forecast_id) WHERE forecast_id IS NOT NULL")
        c.executescript("""
        CREATE TRIGGER IF NOT EXISTS trg_apex49_canonical_forecast_immutable
        BEFORE UPDATE ON apex49_morning_snapshots
        WHEN OLD.forecast_id IS NOT NULL
        BEGIN
          SELECT RAISE(ABORT, 'canonical forecast snapshots are immutable');
        END;
        """)
