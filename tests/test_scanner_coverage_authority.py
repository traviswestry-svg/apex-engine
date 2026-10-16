import datetime as dt
from engine import scanner_coverage_authority as coverage


def test_durable_events_cross_process_and_session(monkeypatch, tmp_path):
    monkeypatch.setenv('APEX_SCANNER_PROCESS', 'true')
    monkeypatch.setenv('APEX_SCANNER_COVERAGE_DB', str(tmp_path / 'coverage.db'))
    timestamp = dt.datetime(2026, 10, 16, 14, 30, tzinfo=dt.timezone.utc)
    assert coverage.record('ATTEMPT', occurred_at=timestamp)
    assert coverage.record('COMPLETED', occurred_at=timestamp, duration=77.2)
    result = coverage.read_coverage('2026-10-16')
    assert result['attempts'] == result['completed'] == 1
    assert result['failures'] == 0
    assert result['boot_instances'] == 1
    assert result['last_event']['duration_seconds'] == 77.2


def test_web_cannot_write_and_read_does_not_create_db(monkeypatch, tmp_path):
    path = tmp_path / 'coverage.db'
    monkeypatch.setenv('APEX_SCANNER_COVERAGE_DB', str(path))
    monkeypatch.delenv('APEX_SCANNER_PROCESS', raising=False)
    assert not coverage.record('ATTEMPT')
    assert coverage.read_coverage()['available'] is False
    assert not path.exists()


def test_et_session_boundary(monkeypatch, tmp_path):
    monkeypatch.setenv('APEX_SCANNER_PROCESS', 'true')
    monkeypatch.setenv('APEX_SCANNER_COVERAGE_DB', str(tmp_path / 'coverage.db'))
    assert coverage.record('FAILED', occurred_at='2026-10-17T01:00:00+00:00')
    assert coverage.read_coverage('2026-10-16')['failures'] == 1
    assert coverage.read_coverage('2026-10-17')['failures'] == 0
