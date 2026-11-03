from datetime import datetime
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from engine.dual_horizon_forecast_integrity import classify_horizon, opening_range_evidence

ET = ZoneInfo('America/New_York')
def at(hour, minute):
    return datetime(2026, 10, 27, hour, minute, tzinfo=ET)
def level(kind, price):
    return SimpleNamespace(kind=SimpleNamespace(value=kind), price=price)

def test_live_revision_not_remaining_move():
    d = classify_horizon(mode='OPENING_DRIVE', source_session_date='2026-10-27',
        target_session_date='2026-10-27', spot=7707.85, expected_move=22.02, now_et=at(9,39))
    assert d['track'] == 'LIVE_REVISION'
    assert d['remaining_session_move_estimated'] is False
    assert d['immutable_baseline_replaced'] is False
    assert d['expected_low'] == 7685.83

def test_premarket_track():
    d = classify_horizon(mode='PREMARKET', source_session_date='2026-10-27',
        target_session_date='2026-10-27', spot=7676.79, expected_move=31.96, now_et=at(9,20))
    assert d['track'] == 'PRE_OUTCOME_OR_SESSION_PREP'

def test_opening_window_missing_after_due():
    d = opening_range_evidence([], now_et=at(9,39), target_session_date='2026-10-27')
    assert d['windows']['or5']['state'] == 'MISSING_AFTER_WINDOW'
    assert d['windows']['or15']['state'] == 'NOT_YET_DUE_OR_DIFFERENT_SESSION'

def test_opening_window_observed():
    d = opening_range_evidence([level('or5_high',7708), level('or5_low',7699)],
        now_et=at(9,39), target_session_date='2026-10-27')
    assert d['windows']['or5']['state'] == 'OBSERVED'

def test_no_prior_session_opening_data_promoted():
    d = opening_range_evidence([], now_et=at(9,39), target_session_date='2026-10-28')
    assert d['windows']['or5']['state'] == 'NOT_YET_DUE_OR_DIFFERENT_SESSION'
