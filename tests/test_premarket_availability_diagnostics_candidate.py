from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from engine.premarket_availability_diagnostics import diagnose
from engine.premarket_directional_features import freeze_features, archive_diagnostics
from engine.premarket_feature_provider import derive_es_features
ET = ZoneInfo('America/New_York')

def at(day, hour=8):
    return datetime.fromisoformat(day).replace(hour=hour, tzinfo=ET).isoformat()

def bar(t, v=100):
    return {'t': int(t.timestamp()*1000), 'c': 6000, 'h': 6001, 'l': 5999, 'v': v}

def sample(day):
    target = datetime.fromisoformat(day).date()
    start = datetime.combine(target-timedelta(days=1), datetime.min.time(), ET).replace(hour=18)
    return {'status':'ok', 'ticker':'ES', 'bars':[bar(start+timedelta(minutes=i*5)) for i in range(169)]}

def test_monday_no_bars_explained_without_fabrication():
    ctx={'status':'unavailable','bars':[]}
    rows=derive_es_features(ctx,decision_at=at('2026-11-02'),target_session_date='2026-11-02')
    reasons=diagnose(ctx,decision_at=at('2026-11-02'),target_session_date='2026-11-02',available=rows)
    assert reasons['feature_reasons']['overnight_es_return']=='ES_PROVIDER_UNAVAILABLE'
    assert reasons['feature_reasons']['gamma_context']=='NO_VERIFIED_DECISION_TIME_GAMMA_INPUT'

def test_sunday_evening_missing_overnight_open():
    ctx=sample('2026-11-02'); ctx['bars']=ctx['bars'][20:]
    r=diagnose(ctx,decision_at=at('2026-11-02'),target_session_date='2026-11-02')
    assert r['feature_reasons']['overnight_es_return']=='OVERNIGHT_OPEN_COVERAGE_MISSING'

def test_target_mismatch_avoids_next_session_reconstruction():
    r=diagnose(sample('2026-11-02'),decision_at=at('2026-10-30',17),target_session_date='2026-11-02')
    assert r['feature_reasons']['overnight_es_return']=='TARGET_SESSION_DATE_MISMATCH'

def test_freeze_and_archive_retain_original_explanations_only():
    c={'status':'unavailable','bars':[]}
    d=diagnose(c,decision_at=at('2026-11-02'),target_session_date='2026-11-02')
    source={'_availability_diagnostics':d}
    frozen=freeze_features(source,decision_at=at('2026-11-02'))
    assert frozen['usable_count']==0
    assert frozen['availability_diagnostics']['feature_reasons']['overnight_es_return']=='ES_PROVIDER_UNAVAILABLE'
    archive={'2026-11-02':{'structured':{'premarket_directional_feature_snapshot':frozen}}}
    before=repr(archive)
    result=archive_diagnostics(archive)
    assert repr(archive)==before
    assert result['details'][0]['availability_diagnostics']==d

def test_legacy_snapshots_no_fabricated_diagnostics():
    frozen=freeze_features({},decision_at=at('2026-10-30'))
    result=archive_diagnostics({'2026-10-30':{'structured':{'premarket_directional_feature_snapshot':frozen}}})
    assert 'availability_diagnostics' not in result['details'][0]

def test_available_is_not_overridden_by_reason():
    c=sample('2026-11-02')
    r=diagnose(c,decision_at=at('2026-11-02'),target_session_date='2026-11-02',
               available={'overnight_es_return':{'value':1}})
    assert r['feature_reasons']['overnight_es_return']=='AVAILABLE'
