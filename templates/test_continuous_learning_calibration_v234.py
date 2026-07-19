import os
from engine.continuous_learning_calibration_v234 import build_continuous_learning, record_outcome

def test_dormant_without_outcomes(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'a.db'))
    x=build_continuous_learning({'ticker':'SPX'})
    assert x['status']=='DORMANT'
    assert x['guardrails']['automatic_weight_mutation'] is False

def test_records_and_calibrates(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'b.db'))
    for i in range(5):
        r=record_outcome({'ticker':'SPX','observed_at':f'2026-07-{10+i:02d}T14:00:00+00:00','playbook_id':'TREND_PULLBACK_CALL','regime':'TREND_EXPANSION','forecast_scenario':'BULL_PATH','stated_confidence':70,'won':i<4,'realized_r':1 if i<4 else -1,'source_id':str(i)})
        assert r['ok']
    x=build_continuous_learning({'ticker':'SPX'})
    assert x['status']=='PROVISIONAL'
    assert x['calibration']['samples']==5
    assert x['performance']['by_playbook'][0]['samples']==5

def test_missing_fields_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'c.db'))
    assert record_outcome({'ticker':'SPX'})['status']=='REJECTED'
