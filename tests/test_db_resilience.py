"""Tests for APEX DB resilience heal + signal_evaluator self-initialization."""
import os

import pytest

from engine import db_resilience


# --------------------------------------------------------------------------- #
# db_resilience.ensure_healthy_db
# --------------------------------------------------------------------------- #
def test_absent_file_is_noop(tmp_path):
    r = db_resilience.ensure_healthy_db(str(tmp_path / "nope.db"))
    assert r["healed"] is False
    assert r["ok"] is True


def test_memory_and_empty_paths_are_noop():
    assert db_resilience.ensure_healthy_db(":memory:")["healed"] is False
    assert db_resilience.ensure_healthy_db("")["healed"] is False


def test_valid_sqlite_is_left_alone(tmp_path):
    import sqlite3
    p = tmp_path / "good.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE t(x)")
    con.commit()
    con.close()
    r = db_resilience.ensure_healthy_db(str(p))
    assert r["healed"] is False
    assert p.exists()  # untouched


def test_corrupt_file_is_quarantined(tmp_path):
    p = tmp_path / "bad.db"
    p.write_bytes(b"this is not a sqlite database, it is garbage bytes " * 10)
    r = db_resilience.ensure_healthy_db(str(p))
    assert r["healed"] is True
    assert "quarantined_to" in r
    assert not p.exists()                     # original moved aside
    assert os.path.exists(r["quarantined_to"])  # preserved, not deleted


def test_heal_is_idempotent_after_quarantine(tmp_path):
    p = tmp_path / "bad2.db"
    p.write_bytes(b"garbage")
    db_resilience.ensure_healthy_db(str(p))   # quarantines
    # file now absent -> second call is a clean no-op
    assert db_resilience.ensure_healthy_db(str(p))["healed"] is False


# --------------------------------------------------------------------------- #
# signal_evaluator self-init (the 'no such table' fix)
# --------------------------------------------------------------------------- #
def test_scorecard_on_fresh_db_does_not_raise_no_such_table(tmp_path, monkeypatch):
    import importlib
    import signal_evaluator as se
    importlib.reload(se)  # reset the cached _READY flag
    monkeypatch.setenv("SIGNAL_EVAL_DB_PATH", str(tmp_path / "fresh.db"))
    se._READY = False
    # scorecard reads pine_signals; on a brand-new DB this used to fail with
    # 'no such table: pine_signals'. Self-init must prevent that.
    result = se.scorecard()
    assert isinstance(result, dict)
    assert "error" not in result or result.get("error") is None


def test_mark_due_on_fresh_db_returns_zero_not_error(tmp_path, monkeypatch):
    import importlib
    import signal_evaluator as se
    importlib.reload(se)
    monkeypatch.setenv("SIGNAL_EVAL_DB_PATH", str(tmp_path / "fresh2.db"))
    se._READY = False

    def _no_bars(*a, **k):
        return []

    n = se.mark_due_signals(_no_bars)
    assert n == 0  # no rows, no crash, table auto-created


def test_evaluator_heals_corrupt_db_then_works(tmp_path, monkeypatch):
    import importlib
    import signal_evaluator as se
    importlib.reload(se)
    dbp = tmp_path / "corrupt_eval.db"
    dbp.write_bytes(b"not a database at all " * 20)
    monkeypatch.setenv("SIGNAL_EVAL_DB_PATH", str(dbp))
    se._READY = False
    # record a signal — heal should quarantine the bad file, init the table,
    # and the insert should succeed.
    se.record_signal({"received_at": "2026-07-21T00:00:00+00:00", "ticker": "SPX",
                      "signal": "CALL", "direction": "BULLISH", "system": "TEST",
                      "price": 5200.0})
    card = se.scorecard()
    assert isinstance(card, dict)
    # the corrupt original was moved aside, a fresh valid DB now exists
    assert dbp.exists()
