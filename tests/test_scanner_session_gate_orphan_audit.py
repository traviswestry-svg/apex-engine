from engine.scanner_session_gate_audit import full_scan_allowed, classify_unresolved
from engine.scanner_coverage_authority import read_coverage, record
import datetime as dt


def test_closed_session_is_gated():
    assert not full_scan_allowed('CLOSED')
    assert full_scan_allowed('OVERNIGHT')
    assert full_scan_allowed('MARKET_OPEN')


def test_unresolved_is_not_failure():
    result = classify_unresolved(152, 151, 0, 0, 'ATTEMPT', 27)
    assert result['state'] == 'RECENT_UNRESOLVED'
    assert result['count'] == 1
    assert classify_unresolved(152, 151, 0, 0, 'ATTEMPT', 700)['state'] == 'STALE_UNRESOLVED_UNCONFIRMED'
    assert classify_unresolved(8, 7, 1, 0, 'FAILED', 5)['state'] == 'NONE'


def test_persisted_audit_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_SCANNER_PROCESS', 'true')
    monkeypatch.setenv('APEX_SCANNER_COVERAGE_DB', str(tmp_path / 'coverage.db'))
    when = dt.datetime.now(dt.timezone.utc)
    assert record('ATTEMPT', occurred_at=when)
    report = read_coverage(when.astimezone(dt.timezone(dt.timedelta(hours=-4))).date().isoformat())
    assert report['available']
    assert report['unresolved_attempts']['count'] == 1
    assert report['unresolved_attempts']['state'] == 'RECENT_UNRESOLVED'
