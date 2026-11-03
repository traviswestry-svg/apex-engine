"""No prep record may steal the same-day canonical forecast slot."""
import datetime as dt
import engine.evening_recap as er
from engine.premarket_directional_features import archived_diagnostics


def brief(mode, when, target='2026-11-02'):
    return {'target_session_date': target, 'session_date': target,
            'generated_at': when, 'session_context': {'brief_mode': mode, 'state': 'PREMARKET' if mode == 'PREMARKET' else 'WEEKEND'},
            'structured': {'spot': 6800.0, 'expected_move': {'one_sigma': 30.0}}}


def test_preparation_then_same_day(monkeypatch, tmp_path):
    monkeypatch.setattr(er, 'DB_PATH', str(tmp_path/'gov.db'))
    prep = er.save_morning_snapshot(brief('NEXT_SESSION_PREP', '2026-10-31T08:00:00-04:00'))
    assert not prep['is_official']
    assert prep['eligibility_reason'] == 'NEXT_SESSION_PREPARATION_NOT_OFFICIAL'
    today = er.save_morning_snapshot(brief('PREMARKET', '2026-11-02T08:15:00-05:00'))
    assert today['is_official'] and today['forecast_id']
    assert er.get_morning_snapshot('2026-11-02')['generated_at'] == '2026-11-02T08:15:00-05:00'
    result = archived_diagnostics(limit=10)
    lifecycle = result['details'][0]['lifecycle']
    assert lifecycle['revision_count'] == 2
    assert lifecycle['brief_modes'] == {'NEXT_SESSION_PREP': 1, 'PREMARKET': 1}
    assert lifecycle['classification'] == 'CANONICAL_SAME_DAY_ARCHIVED'


def test_preparation_only_is_not_official(monkeypatch, tmp_path):
    monkeypatch.setattr(er, 'DB_PATH', str(tmp_path/'gov.db'))
    result = er.save_morning_snapshot(brief('NEXT_SESSION_PREP', '2026-10-31T08:00:00-04:00'))
    assert result['is_official'] is False
    assert er.get_morning_snapshot('2026-11-02') is None


def test_same_day_only_then_revision_immutable(monkeypatch, tmp_path):
    monkeypatch.setattr(er, 'DB_PATH', str(tmp_path/'gov.db'))
    original = er.save_morning_snapshot(brief('PREMARKET', '2026-11-02T08:00:00-05:00'))
    later = er.save_morning_snapshot(brief('PREMARKET', '2026-11-02T08:30:00-05:00'))
    assert original['is_official'] and not later['is_official']
    assert original['forecast_id'] == later['forecast_id']


def test_previous_day_premarket_not_official():
    eligible, reason, _ = er._official_forecast_eligibility(
        brief('PREMARKET', '2026-10-31T08:00:00-04:00'))
    assert not eligible and reason == 'NOT_SAME_DAY_PREMARKET'
