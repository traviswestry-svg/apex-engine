from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from engine.premarket_feature_provider import derive_es_features
from engine.premarket_directional_features import freeze_features

ET = ZoneInfo('America/New_York')

def sample():
    start = datetime(2026,10,29,18,0,tzinfo=ET)
    bars = [{'t':int((start+timedelta(minutes=i*5)).timestamp()*1000),
             'c':7000+i,'h':7001+i,'l':6999+i,'v':100+i} for i in range(3)]
    prior = datetime(2026,10,29,17,55,tzinfo=ET)
    return {'status':'ok','ticker':'ESZ26','bars':bars,'prev_settlement':6990,
            'prev_settlement_bar_at':int(prior.timestamp()*1000),
            'settlement_method':'previous_session_close_proxy'}

def test_verified_bar_derivation():
    # Use the October 29 overnight session, for the October 30 forecast.
    ctx=sample()
    recent=datetime(2026,10,30,7,45,tzinfo=ET)
    ctx['bars'].append({'t':int(recent.timestamp()*1000),'c':7010,'h':7011,'l':7009,'v':110})
    at=datetime(2026,10,30,8,0,tzinfo=ET).isoformat()
    rows=derive_es_features(ctx,decision_at=at,target_session_date='2026-10-30')
    assert set(rows)=={'overnight_es_return','overnight_vwap_displacement','premarket_gap'}
    frozen=freeze_features(rows,decision_at=at)
    assert frozen['usable_count']==3

def test_current_bar_accepted():
    ctx=sample()
    at=datetime(2026,10,29,18,20,tzinfo=ET).isoformat()
    assert derive_es_features(ctx,decision_at=at,target_session_date='2026-10-30')=={}

def test_after_open_rejected():
    ctx=sample()
    at=datetime(2026,10,30,9,31,tzinfo=ET).isoformat()
    assert derive_es_features(ctx,decision_at=at,target_session_date='2026-10-30')=={}

def test_no_provider_no_fabrication():
    at=datetime(2026,10,30,8,0,tzinfo=ET).isoformat()
    assert derive_es_features({},decision_at=at,target_session_date='2026-10-30')=={}
