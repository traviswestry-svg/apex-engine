"""Read-only canonical range integrity and exact outcome consistency tests."""
from copy import deepcopy
from engine.morning_forecast_shadow_calibration import extract_observation
from engine.premarket_directional_features import forecast_center_integrity, shadow_outcome_attribution
from test_premarket_magnitude_conflict_outcome_candidate import DAY, morning, recap


def test_center_residual_decomposition_and_containment():
    m = morning(); r = recap(actual_low=96, actual_high=106)
    original = deepcopy((m,r))
    audit = forecast_center_integrity(m, r, extract_observation(r))
    assert audit['status'] == 'VERIFIED'
    assert audit['center_residual_points'] == 1
    assert audit['high_error_points'] == -4
    assert audit['low_error_points'] == 6
    assert audit['width_error_points'] == -10
    assert audit['contained_from_frozen_bounds'] is True
    assert (m,r) == original


def test_failed_containment_and_miss_decomposition():
    m=morning(); r=recap(actual_low=80, actual_high=106)
    r['comparison']['checks'][0]['correct']=False
    audit=forecast_center_integrity(m,r,extract_observation(r))
    assert audit['status']=='VERIFIED'
    assert audit['low_excess_points']==10
    assert audit['high_excess_points']==0
    assert audit['contained_from_frozen_bounds'] is False


def test_mismatched_original_range_rejected():
    m=morning(); r=recap()
    m['structured']['expected_move']['upper']=120
    audit=forecast_center_integrity(m,r,extract_observation(r))
    assert audit['status']=='INCONSISTENT'
    assert 'RECAP_PROJECTED_BOUNDS_DO_NOT_MATCH_FROZEN_FORECAST' in audit['issues']
    result=shadow_outcome_attribution({DAY:m},[r])
    assert result['eligible_sessions']==0
    assert result['excluded_reasons']['FORECAST_CENTER_INTEGRITY_INCONSISTENT']==1


def test_official_containment_mismatch_rejected():
    m=morning(); r=recap()
    r['comparison']['checks'][0]['correct']=False
    audit=forecast_center_integrity(m,r,extract_observation(r))
    assert audit['status']=='INCONSISTENT'
    assert 'OFFICIAL_CONTAINMENT_BOOLEAN_MISMATCH' in audit['issues']


def test_missing_frozen_range_not_inferred_from_recap():
    m=morning(); r=recap()
    del m['structured']['expected_move']
    audit=forecast_center_integrity(m,r,extract_observation(r))
    assert audit['status']=='UNVERIFIABLE'
    assert 'FROZEN_EXPECTED_RANGE_INVALID_OR_ABSENT' in audit['issues']


def test_extra_diagnostic_inconsistent_rejected():
    m=morning(); r=recap()
    r['comparison']['forecast_error_diagnostics']={'range':{'available':True,'center_error_points':50.0,'contained':True}}
    audit=forecast_center_integrity(m,r,extract_observation(r))
    assert audit['status']=='INCONSISTENT'
    assert 'OFFICIAL_CENTER_ERROR_DIAGNOSTIC_MISMATCH' in audit['issues']
