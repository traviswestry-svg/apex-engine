"""Low-level APEX 49 archive schema bootstrap.

This module deliberately has no dependency on ``engine.evening_recap``.  Startup
and read-model code can therefore ensure the archive schema exists without
importing the recap service while the Flask application is still initializing.
"""
from __future__ import annotations

import os
import sqlite3


def init_evening_archive_db(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    with sqlite3.connect(db_path, timeout=10) as c:
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
