import sqlite3
from pathlib import Path

from engine.evidence_audit import evidence_audit


def _cal_db(path: Path):
    with sqlite3.connect(path) as c:
        c.executescript('''
        CREATE TABLE daily_levels(level_id TEXT, session_date TEXT, registered_at TEXT);
        CREATE TABLE level_interactions(interaction_id TEXT, session_date TEXT, ts TEXT);
        CREATE TABLE level_outcomes(outcome_id TEXT, session_date TEXT, graded_at TEXT);
        CREATE TABLE level_transition_observations(observation_id TEXT, session_date TEXT, created_at TEXT);
        CREATE TABLE level_transition_statistics(stat_id TEXT, updated_at TEXT);
        INSERT INTO daily_levels VALUES('d1','2026-08-01','2026-08-01T12:00:00Z');
        INSERT INTO level_interactions VALUES('i1','2026-08-01','2026-08-01T13:00:00Z');
        INSERT INTO level_outcomes VALUES('o1','2026-08-01','2026-08-01T13:30:00Z');
        INSERT INTO level_transition_observations VALUES('t1','2026-08-01','2026-08-01T13:31:00Z');
        INSERT INTO level_transition_statistics VALUES('s1','2026-08-01T13:32:00Z');
        ''')


def _gov_db(path: Path):
    with sqlite3.connect(path) as c:
        c.executescript('''
        CREATE TABLE apex49_morning_snapshots(session_date TEXT, generated_at TEXT);
        CREATE TABLE apex49_morning_revisions(session_date TEXT, generated_at TEXT);
        CREATE TABLE apex49_evening_recaps(session_date TEXT, generated_at TEXT);
        CREATE TABLE apex5071_readiness_archive(session_date TEXT, captured_at TEXT);
        INSERT INTO apex49_morning_snapshots VALUES('2026-08-01','2026-08-01T11:00:00Z');
        INSERT INTO apex49_morning_revisions VALUES('2026-08-01','2026-08-01T11:00:00Z');
        INSERT INTO apex49_evening_recaps VALUES('2026-08-01','2026-08-01T21:00:00Z');
        INSERT INTO apex5071_readiness_archive VALUES('2026-08-01','2026-08-01T10:00:00Z');
        ''')


def test_evidence_audit_counts_and_semantics(tmp_path):
    cal = tmp_path / 'cal.db'; gov = tmp_path / 'gov.db'
    _cal_db(cal); _gov_db(gov)
    result = evidence_audit(calibration_path=str(cal), governance_path=str(gov))
    assert result['status'] == 'HEALTHY'
    assert result['read_only'] is True
    assert result['summary']['level_interactions'] == 1
    assert result['summary']['level_transition_observations'] == 1
    assert result['summary']['official_morning_briefs'] == 1
    assert 'not historical sample size' in result['semantics']['evening_recap_touch_count']


def test_evidence_audit_missing_db_is_partial_not_exception(tmp_path):
    result = evidence_audit(calibration_path=str(tmp_path/'missing-cal.db'), governance_path=str(tmp_path/'missing-gov.db'))
    assert result['status'] == 'PARTIAL'
    assert result['summary']['level_interactions'] == 0


def test_route_source_contains_evidence_audit_endpoint():
    source = Path('engine/historical_level_calibration_routes.py').read_text()
    assert '/api/level-calibration/evidence-audit' in source
    assert 'EVIDENCE_AUDIT_ROUTE_BOUNDARY' in source


def test_recap_labels_touch_count_as_bar_touches():
    source = Path('engine/evening_recap.py').read_text()
    assert '| Level | Price | Bar Touches | Outcome |' in source
    assert '| Level | Price | Tests | Outcome |' not in source
