import datetime as dt
import sqlite3
from engine import scanner_coverage_authority as journal

NOW = dt.datetime.now(dt.timezone.utc)


def setup(monkeypatch, tmp_path):
    monkeypatch.setenv('APEX_SCANNER_PROCESS', 'true')
    monkeypatch.setenv('APEX_SCANNER_COVERAGE_DB', str(tmp_path / 'journal.db'))
    return tmp_path / 'journal.db'


def test_correlated_lifecycle_and_duplicate_terminal_rejected(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    assert journal.record('ATTEMPT', attempt_id='cycle-1', occurred_at=NOW)
    assert journal.record('COMPLETED', attempt_id='cycle-1', occurred_at=NOW, duration=1.2)
    assert not journal.record('FAILED', attempt_id='cycle-1', occurred_at=NOW)
    assert not journal.record('ATTEMPT', attempt_id='cycle-1', occurred_at=NOW)
    r = journal.read_coverage(NOW.astimezone(journal._ET).date().isoformat())
    assert r['attempt_reconciliation']['paired_terminal_events'] == 1
    assert r['attempt_reconciliation']['stale_open'] == 0
    assert r['failures'] == 0


def test_unpaired_old_attempt_is_diagnostic_not_failure(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    old = NOW - dt.timedelta(minutes=30)
    assert journal.record('ATTEMPT', attempt_id='old-cycle', occurred_at=old)
    r = journal.read_coverage(old.astimezone(journal._ET).date().isoformat())
    assert r['attempt_reconciliation']['stale_open'] == 1
    assert r['attempt_reconciliation']['stale_classification'] == 'UNCONFIRMED_NOT_A_FAILURE'
    assert r['failures'] == 0


def test_additive_legacy_schema_migration(monkeypatch, tmp_path):
    path = setup(monkeypatch, tmp_path)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE scanner_events (id TEXT PRIMARY KEY, boot_id TEXT NOT NULL, pid INTEGER NOT NULL, session_date TEXT NOT NULL, occurred_at TEXT NOT NULL, event TEXT NOT NULL, duration REAL, reason TEXT)')
        db.execute('INSERT INTO scanner_events VALUES (?,?,?,?,?,?,?,?)', ('legacy', 'boot-old', 1, NOW.astimezone(journal._ET).date().isoformat(), NOW.isoformat(), 'ATTEMPT', None, None))
    assert journal.record('ATTEMPT', attempt_id='new', occurred_at=NOW)
    r = journal.read_coverage(NOW.astimezone(journal._ET).date().isoformat())
    assert r['attempt_reconciliation']['legacy_uncorrelated_attempts'] == 1
    assert r['attempt_reconciliation']['correlated_attempts'] == 1


def test_web_read_only_and_unpaired_terminal_rejected(monkeypatch, tmp_path):
    path = setup(monkeypatch, tmp_path)
    assert journal.record('ATTEMPT', attempt_id='live', occurred_at=NOW)
    assert not journal.record('COMPLETED', attempt_id='missing', occurred_at=NOW)
    monkeypatch.setenv('APEX_SCANNER_PROCESS', 'false')
    assert not journal.record('COMPLETED', attempt_id='live', occurred_at=NOW)
    assert journal.read_coverage(NOW.astimezone(journal._ET).date().isoformat())['attempt_reconciliation']['recent_open'] == 1
