"""Frozen magnitude diagnostics and exact-canonical, retrospective outcome attribution."""
from copy import deepcopy
from engine.premarket_directional_features import (
    freeze_features, magnitude_conflict_diagnostics, shadow_outcome_attribution,
    shadow_direction, archive_diagnostics,
)

DAY = '2026-11-03'
AT = '2026-11-03T06:18:12-05:00'

def feature(value):
    return {'value': value, 'observed_at': '2026-11-03T06:10:00-05:00',
            'ingested_at': '2026-11-03T06:17:00-05:00', 'source': 'ESZ6',
            'decision_time_verified': True}

def snapshot(vwap=1.865):
    return freeze_features({
        'overnight_es_return': feature(-0.0495),
        'premarket_gap': feature(-0.0858),
        'overnight_vwap_displacement': feature(vwap),
        'premarket_trend_strength': feature(0.0),
        'prior_day_range_position': feature(-0.008),
    }, decision_at=AT)

def morning(snap=None, mode='PREMARKET', generated=AT):
    return {'generated_at': generated, 'session_context': {'brief_mode':mode},
            'canonical_forecast_provenance': {'forecast_id':'fcst1', 'snapshot_hash':'hash1'},
            'structured': {'expected_move': {'lower':90.0,'upper':110.0}, 'spot':100.0,
                           'premarket_directional_feature_snapshot': snap or snapshot()}}

def recap(forecast_id='fcst1', hash='hash1', actual_low=96, actual_high=106):
    return {'session_date': DAY, 'forecast_id':forecast_id, 'forecast_snapshot_hash':hash,
            'comparison': {'actual':{'available':True, 'low':actual_low, 'high':actual_high},
                           'checks':[{'key':'expected_move_containment','projected':'90 to 110','correct': (actual_low >= 90 and actual_high <= 110)},
                                     {'key':'expected_move_size','projected':10,'actual':8,
                                      'reference_spot':100,
                                      'actual_metric':'MAX_ABS_EXCURSION_FROM_FROZEN_MORNING_SPOT'}]}}

def test_vwap_recovery_typology_and_original_abstention_unchanged():
    snap=snapshot(); original=deepcopy(snap)
    result=magnitude_conflict_diagnostics(snap)
    assert result['conflict_type']=='VWAP_RECOVERY_AGAINST_NEGATIVE_OVERNIGHT'
    assert result['features']['overnight_es_return']['unit']=='PERCENT'
    assert result['features']['overnight_vwap_displacement']['unit']=='ES_POINTS'
    assert result['features']['premarket_trend_strength']['absolute_magnitude']==0.0
    assert shadow_direction(snap)['direction'] is None
    assert snap==original

def test_negative_unanimity_and_missing_input():
    assert magnitude_conflict_diagnostics(snapshot(-5))['conflict_type']=='UNANIMOUS_NEGATIVE_ES'
    snap=snapshot(); snap['features']['premarket_gap']={'status':'STALE','value':None}
    assert magnitude_conflict_diagnostics(snap)['conflict_type']=='INCOMPLETE_REQUIRED_EVIDENCE'

def test_exact_identity_outcome_join_and_metric_semantics():
    m=morning(); r=recap(); old=deepcopy((m,r))
    result=shadow_outcome_attribution({DAY:m},[r])
    assert result['eligible_sessions']==1
    assert result['comparison_ready'] is False
    row=result['rows'][0]
    assert row['forecast_center_residual_points']==1.0
    assert row['residual_direction']=='ABOVE_FORECAST_CENTER'
    assert row['forecast_contained_actual_range'] is True
    assert row['shadow_direction'] is None
    assert (m,r)==old

def test_mismatched_identity_missing_recap_and_future_preparation_excluded():
    m=morning()
    assert shadow_outcome_attribution({DAY:m},[recap(forecast_id='wrong')])['excluded_reasons']['EXACT_CANONICAL_IDENTITY_MISMATCH']==1
    assert shadow_outcome_attribution({DAY:m},[])['excluded_reasons']['NO_COMPLETED_RECAP']==1
    assert shadow_outcome_attribution({DAY:morning(mode='NEXT_SESSION_PREP')},[recap()])['excluded_reasons']['INVALID_CANONICAL_ORIGIN']==1
    assert shadow_outcome_attribution({DAY:morning(generated='2026-11-02T06:18:12-05:00')},[recap()])['eligible_sessions']==0

def test_duplicate_recaps_and_incomplete_realized_data_rejected():
    assert shadow_outcome_attribution({DAY:morning()},[recap(),recap()])['excluded_reasons']['AMBIGUOUS_DUPLICATE_RECAP']==1
    bad=recap(); bad['comparison']['actual']['available']=False
    assert shadow_outcome_attribution({DAY:morning()},[bad])['excluded_reasons']['OUTCOME_INCOMPLETE_OR_INCOMPATIBLE']==1

def test_frozen_only_diagnostic_does_not_fill_old_snapshots():
    no_snapshot={'generated_at': AT,'structured':{}}
    result=archive_diagnostics({DAY:no_snapshot})
    assert 'magnitude_conflict_diagnostics' not in result['details'][0]
    assert result['details'][0]['status']=='SNAPSHOT_NOT_ARCHIVED'

def test_invalid_minimum_and_no_accuracy_claim():
    try:
        shadow_outcome_attribution({},[],min_samples=1)
    except ValueError:
        pass
    else:
        raise AssertionError('invalid minimum accepted')
    assert shadow_outcome_attribution({},[])['accuracy_claim'] is False
