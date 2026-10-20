"""Durable, observation-only cursor for future bounded flow-learning batches.

This module does not authorize execution or change evidence ownership. A cursor is
advanced only after its caller has committed the corresponding canonical writes.
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Cursor:
    session_date: str
    source_fingerprint: str
    next_index: int
    completed: bool


class CheckpointStore:
    def __init__(self, path: str):
        self.path = path

    def _connect(self):
        parent = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(parent, exist_ok=True)
        con = sqlite3.connect(self.path, timeout=10)
        con.execute("PRAGMA busy_timeout=10000")
        con.execute("""CREATE TABLE IF NOT EXISTS flow_learning_checkpoint (
            session_date TEXT NOT NULL,
            source_fingerprint TEXT NOT NULL,
            next_index INTEGER NOT NULL CHECK(next_index >= 0),
            completed INTEGER NOT NULL CHECK(completed IN (0,1)),
            PRIMARY KEY(session_date, source_fingerprint))""")
        return con

    def read(self, session_date: str, source_fingerprint: str) -> Cursor:
        with self._connect() as con:
            row = con.execute("SELECT next_index, completed FROM flow_learning_checkpoint "
                              "WHERE session_date=? AND source_fingerprint=?",
                              (session_date, source_fingerprint)).fetchone()
        return Cursor(session_date, source_fingerprint, int(row[0]) if row else 0,
                      bool(row[1]) if row else False)

    def advance(self, session_date: str, source_fingerprint: str,
                expected_index: int, next_index: int, *, completed: bool = False) -> bool:
        """CAS update. Caller MUST commit evidence first; never rewind progress."""
        if not session_date or not source_fingerprint or expected_index < 0 or next_index < expected_index:
            raise ValueError("Invalid checkpoint advance")
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT next_index, completed FROM flow_learning_checkpoint "
                              "WHERE session_date=? AND source_fingerprint=?",
                              (session_date, source_fingerprint)).fetchone()
            actual = int(row[0]) if row else 0
            if actual != expected_index or (row and row[1]):
                return False
            con.execute("""INSERT INTO flow_learning_checkpoint
                        (session_date, source_fingerprint, next_index, completed)
                        VALUES (?, ?, ?, ?) ON CONFLICT(session_date, source_fingerprint)
                        DO UPDATE SET next_index=excluded.next_index, completed=excluded.completed""",
                        (session_date, source_fingerprint, next_index, int(completed)))
        return True
