from engine.premarket_directional_features import freeze_features, shadow_direction, archive_diagnostics

DECISION = '2026-10-29T09:20:00-04:00'

def row(value, observed='2026-10-29T09:18:00-04:00', ingested='2026-10-29T09:19:00-04:00'):
    return {'value': value, 'source': 'VERIFIED_TEST_FEED', 'observed_at': observed,
            'ingested_at': ingested, 'decision_time_verified': True}

def test_rejects_future_and_stale():
    snap=freeze_features({'overnight_es_return': row(2, observed='2026-10-29T09:21:00-04:00'),
       'premarket_gap': row(3, observed='2026-10-29T08:00:00-04:00')},decision_at=DECISION)
    assert snap['usable_count']==0
    assert snap['features']['overnight_es_return']['status']=='FUTURE_EVIDENCE_REJECTED'
    assert snap['features']['premarket_gap']['status']=='STALE'

def test_requires_provenance_and_rejects_non_numeric():
    snap=freeze_features({'premarket_gap': {'value': 2},
         'overnight_es_return': row(float('nan'))},decision_at=DECISION)
    assert snap['usable_count']==0
    assert snap['features']['premarket_gap']['status']=='UNVERIFIED_PROVENANCE'
    assert snap['features']['overnight_es_return']['status']=='INVALID_VALUE'

def test_three_verified_signals_agree():
    snap=freeze_features({key: row(2) for key in
        ('overnight_es_return','overnight_vwap_displacement','premarket_gap')}, decision_at=DECISION)
    assert shadow_direction(snap)['direction']=='BULLISH'
    assert shadow_direction(snap)['regime'] is None
    assert shadow_direction(freeze_features({},decision_at=DECISION))['direction'] is None

def test_conflict_abstains():
    snap=freeze_features({'overnight_es_return':row(1),
         'overnight_vwap_displacement':row(-1), 'premarket_gap':row(1)},decision_at=DECISION)
    assert shadow_direction(snap)['direction'] is None

def test_missing_historical_archive_not_backfilled():
    report=archive_diagnostics({'2026-10-29':{'structured':{}}})
    assert report['status_counts']=={'SNAPSHOT_NOT_ARCHIVED':1}
    assert report['production_promotion'] is False
