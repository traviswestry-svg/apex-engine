import sqlite3

import pytest

from engine.canonical_persistence import connect, connection, diagnostics, transaction
from engine import evidence_pipeline


def test_canonical_connection_enforces_policy(tmp_path):
    db = tmp_path / "policy.db"
    with connection(db) as conn:
        conn.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE child(id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))")
        conn.commit()
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] > 0


def test_transaction_commits_and_rolls_back(tmp_path):
    db = tmp_path / "tx.db"
    with connection(db) as conn:
        conn.execute("CREATE TABLE t(v INTEGER)")
        conn.commit()

    with transaction(db) as conn:
        conn.execute("INSERT INTO t(v) VALUES(1)")

    with pytest.raises(RuntimeError):
        with transaction(db) as conn:
            conn.execute("INSERT INTO t(v) VALUES(2)")
            raise RuntimeError("force rollback")

    with connection(db, read_only=True, wal=False, heal=False) as conn:
        assert [r[0] for r in conn.execute("SELECT v FROM t ORDER BY v")] == [1]


def test_read_only_connection_rejects_write(tmp_path):
    db = tmp_path / "readonly.db"
    with connection(db) as conn:
        conn.execute("CREATE TABLE t(v INTEGER)")
        conn.commit()

    with connection(db, read_only=True, wal=False, heal=False) as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO t(v) VALUES(1)")


def test_diagnostics_reports_integrity(tmp_path):
    db = tmp_path / "diag.db"
    with connection(db) as conn:
        conn.execute("CREATE TABLE t(v INTEGER)")
        conn.commit()
    d = diagnostics(db)
    assert d["ok"] is True
    assert d["integrity"] == "ok"
    assert d["journal_mode"].lower() == "wal"


def test_evidence_pipeline_uses_canonical_policy(tmp_path):
    db = tmp_path / "evidence.db"
    with evidence_pipeline._connect(db) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.row_factory is sqlite3.Row
