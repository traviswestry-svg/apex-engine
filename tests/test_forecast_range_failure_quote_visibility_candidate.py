"""Read-only research integrity and decomposition regression tests."""
import copy
from engine.premarket_directional_features import (
    forecast_range_failure_decomposition, frozen_option_quote_integrity_visibility,
    archive_diagnostics,
)


def audited(fl=7670.885, fh=7769.315, al=7527.56, ah=7637.48):
    return {'status': 'VERIFIED', 'forecast_low': fl, 'forecast_high': fh,
            'actual_low': al, 'actual_high': ah}


def test_oct_30_both_width_and_placement():
    r = forecast_range_failure_decomposition(audited())
    assert r['status'] == 'VERIFIED'
    assert r['failure_type'] == 'WIDTH_INSUFFICIENT_AND_PLACEMENT_MISMATCH'
    assert r['minimum_total_width_shortfall_points'] == 11.49
    assert r['center_residual_points'] == -137.58
    assert r['lower_boundary_excess_points'] == 143.325
    assert r['fixed_width_feasible_center_interval'] is None


def test_nov_4_placement_only_and_feasible_center_interval():
    r = forecast_range_failure_decomposition(audited(7495.88,7641.06,7635.81,7715.57))
    assert r['failure_type'] == 'PLACEMENT_ONLY_WIDTH_SUFFICIENT'
    assert r['minimum_total_width_shortfall_points'] == 0
    assert r['upper_boundary_excess_points'] == 74.51
    assert r['minimum_fixed_width_center_shift_points'] == 74.51
    assert r['fixed_width_feasible_center_interval'] is not None


def test_contained_case_has_zero_excess_and_no_shift():
    r = forecast_range_failure_decomposition(audited(90,110,95,105))
    assert r['failure_type'] == 'CONTAINED'
    assert r['fixed_center_required_additional_half_width_points'] == 0
    assert r['minimum_fixed_width_center_shift_points'] == 0


def test_aligned_center_but_width_too_narrow():
    r = forecast_range_failure_decomposition(audited(95,105,90,110))
    assert r['failure_type'] == 'WIDTH_INSUFFICIENT_CENTER_ALIGNED'
    assert r['minimum_total_width_shortfall_points'] == 10


def test_unverified_integrity_is_never_decomposed():
    for data in ({}, {'status': 'INCONSISTENT'}, audited(10,10,9,11)):
        assert forecast_range_failure_decomposition(data)['status'] == 'UNVERIFIABLE'


def test_quote_visibility_legacy_cannot_be_upgraded():
    legacy = {'structured': {'forecast_provenance_diagnostics': {'expected_move': {
        'quote_timestamp': '2026-11-03T22:00:00+00:00', 'selected_path': 'STRADDLE_FIRST',
    }}}}
    result = frozen_option_quote_integrity_visibility(legacy)
    assert result['status'] == 'LEGACY_SOURCE_AUDIT_NOT_ARCHIVED'
    assert result['source_integrity'] is None


def test_quote_visibility_exact_frozen_status_and_legs():
    audit = {'schema': 'EXPECTED_MOVE_DECISION_TIME_SOURCE_INTEGRITY_V1',
             'status': 'DEGRADED_SOURCE_EVIDENCE', 'provider_source_verified': False,
             'issues': ['STALE_QUOTE_CALL'], 'quote_legs': {'call': {'bid': 15.0, 'ask': 16.0,
              'provider_quote_timestamp':'2026-11-03T22:00:00+00:00'}}}
    morning = {'structured': {'forecast_provenance_diagnostics': {'expected_move': {
        'decision_time_source_integrity': copy.deepcopy(audit)}}}}
    response = frozen_option_quote_integrity_visibility(morning)
    assert response['status'] == 'FROZEN_SOURCE_AUDIT_AVAILABLE'
    assert response['source_integrity'] == audit
    assert response['source_status'] == 'DEGRADED_SOURCE_EVIDENCE'
    assert response['provider_source_verified'] is False
    assert response['official_forecast_mutated'] is False


def test_archive_reader_exposes_only_existing_frozen_audit():
    snapshot = {'schema': 'PREMARKET_DIRECTIONAL_FEATURES_V1', 'decision_at': '2026-11-04T10:00:00+00:00',
                'features': {}, 'usable_count': 0}
    morning = {'generated_at':'2026-11-04T10:00:00+00:00',
               'brief_mode':'PREMARKET', 'structured':{'premarket_directional_feature_snapshot': snapshot}}
    result = archive_diagnostics({'2026-11-04':morning})['details'][0]
    assert result['option_quote_integrity_visibility']['status'] == 'LEGACY_SOURCE_AUDIT_NOT_ARCHIVED'
