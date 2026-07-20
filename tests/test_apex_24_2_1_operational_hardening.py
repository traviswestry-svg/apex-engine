import json
import os
from pathlib import Path

from engine import operational_runtime as runtime


def test_persistent_path_respects_explicit_environment(monkeypatch, tmp_path):
    target = tmp_path / "custom.db"
    monkeypatch.setenv("CUSTOM_DB", str(target))
    assert runtime.persistent_path("fallback.db", "CUSTOM_DB") == str(target)


def test_connect_sqlite_applies_runtime_policy(tmp_path):
    conn = runtime.connect_sqlite(str(tmp_path / "runtime.db"))
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000
        conn.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()


def test_scanner_heartbeat_round_trip(monkeypatch, tmp_path):
    path = tmp_path / "heartbeat.json"
    monkeypatch.setenv("APEX_SCANNER_HEARTBEAT_PATH", str(path))
    runtime.write_scanner_heartbeat({"scanner_started": True})
    payload = runtime.read_scanner_heartbeat()
    assert payload["available"] is True
    assert payload["scanner_started"] is True
    assert payload["age_seconds"] >= 0


def test_storage_status_is_measurement(monkeypatch, tmp_path):
    monkeypatch.setenv("APEX_PERSISTENT_DISK_PATH", str(tmp_path))
    (tmp_path / "sample.db").write_bytes(b"1234")
    status = runtime.storage_status()
    assert status["root"] == str(tmp_path.resolve())
    assert status["database_bytes"] >= 4
    assert status["state"] in {"PASS", "WARNING", "CRITICAL"}
