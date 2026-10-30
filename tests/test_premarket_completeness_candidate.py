from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from engine.premarket_feature_provider import derive_es_features
from engine.premarket_directional_features import freeze_features, archive_diagnostics
ET=ZoneInfo('America/New_York')

def bar(t,c):
    return {'t':int(t.timestamp()*1000),'c':c,'h':c+1,'l':c-1,'v':100}

def context():
    start=datetime(2026,10,29,18,tzinfo=ET)
    bars=[bar(start+timedelta(minutes=5*i),7000+i*.1) for i in range(168)]
    rth=datetime(2026,10,29,9,30,tzinfo=ET)
    prior=[bar(rth+timedelta(minutes=5*i),6990+i*.2) for i in range(78)]
    return {'status':'ok','ticker':'ES','bars':bars,'prior_rth_bars':prior}

def at(): return datetime(2026,10,30,8,5,tzinfo=ET).isoformat()

def test_completed_prior_range_and_trend():
    rows=derive_es_features(context(),decision_at=at(),target_session_date='2026-10-30')
    assert 'prior_day_range_position' in rows
    assert 'premarket_trend_strength' in rows
    assert 'gamma_context' not in rows
    frozen=freeze_features(rows,decision_at=at())
    assert frozen['features']['prior_day_range_position']['status']=='AVAILABLE'
    assert frozen['features']['premarket_trend_strength']['status']=='AVAILABLE'
    assert frozen['features']['gamma_context']['status']=='MISSING'

def test_partial_prior_range_abstains():
    ctx=context();ctx['prior_rth_bars']=ctx['prior_rth_bars'][:30]
    rows=derive_es_features(ctx,decision_at=at(),target_session_date='2026-10-30')
    assert 'prior_day_range_position' not in rows

def test_discontinuous_trend_abstains():
    ctx=context();del ctx['bars'][-3]
    rows=derive_es_features(ctx,decision_at=at(),target_session_date='2026-10-30')
    assert 'premarket_trend_strength' not in rows

def test_future_prior_bar_rejected():
    ctx=context();ctx['prior_rth_bars']=[bar(datetime(2026,10,30,9,30,tzinfo=ET)+timedelta(minutes=i*5),7000) for i in range(78)]
    assert 'prior_day_range_position' not in derive_es_features(ctx,decision_at=at(),target_session_date='2026-10-30')

def test_archive_diagnostic_does_not_modify_prior_snapshots():
    row={'structured':{'premarket_directional_feature_snapshot': freeze_features(
        derive_es_features(context(),decision_at=at(),target_session_date='2026-10-30'),decision_at=at())}}
    before=repr(row)
    result=archive_diagnostics({'2026-10-30':row})
    assert result['sessions']==1 and repr(row)==before
