import datetime as dt
import sqlite3
from engine.scanner_freshness_deadline import deadline_plan
from engine.scanner_coverage_authority import read_coverage


def test_flow_learning_is_deferred_when_next_scan_and_work_do_not_fit():
    plan = deadline_plan(180, 60, 75, margin_seconds=45, optional_work_estimate_seconds=120)
    assert not plan.allow_optional_work
    assert plan.sleep_seconds == 0


def test_short_optional_work_can_run_with_budget():
    assert deadline_plan(180, 5, 60, margin_seconds=20,
                         optional_work_estimate_seconds=15).allow_optional_work


def test_journal_exposes_last_completion_even_when_new_attempt_is_latest(tmp_path, monkeypatch):
    path = tmp_path / 'scanner.db'
    monkeypatch.setenv('APEX_SCANNER_COVERAGE_DB', str(path))
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=-4))).date().isoformat()
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE scanner_events (id TEXT PRIMARY KEY, boot_id TEXT NOT NULL, pid INTEGER NOT NULL, session_date TEXT NOT NULL, occurred_at TEXT NOT NULL, event TEXT NOT NULL, duration REAL, reason TEXT)')
        db.execute('INSERT INTO scanner_events VALUES (?,?,?,?,?,?,?,?)', ('a','boot',65,today,'2026-10-19T18:48:30+00:00','COMPLETED',60,None))
        db.execute('INSERT INTO scanner_events VALUES (?,?,?,?,?,?,?,?)', ('b','boot',65,today,'2026-10-19T18:49:00+00:00','ATTEMPT',None,None))
    result = read_coverage(session_date=today)
    assert result['last_event']['event'] == 'ATTEMPT'
    assert result['last_completed_event']['event'] == 'COMPLETED'
    assert result['last_completed_event']['duration_seconds'] == 60
