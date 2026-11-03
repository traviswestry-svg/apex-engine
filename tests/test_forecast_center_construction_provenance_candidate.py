"""Read-only frozen construction audit and fixed displacement sensitivity tests."""
from copy import deepcopy
from engine.premarket_directional_features import (
    forecast_center_construction_provenance,
    shadow_directional_center_sensitivity,
    shadow_outcome_attribution,
)
from test_premarket_magnitude_conflict_outcome_candidate import DAY, morning, recap


def archived_morning():
    m = morning()
    m['structured']['expected_move']['one_sigma'] = 10.0
    m['structured']['forecast_provenance_diagnostics'] = {'expected_move': {
        'reference_spot': 100., 'selected_one_sigma': 10.,
        'upper': 110., 'lower': 90., 'selected_path': 'STRADDLE_FIRST',
        'straddle_implied_one_sigma': 10., 'iv_implied_one_sigma': 9.5,
        'quote_timestamp': None, 'option_expiration': None,
        'missing_source_metadata': ['quote_timestamp', 'option_expiration']}}
    return m


def test_frozen_construction_arithmetic_and_unverified_provider():
    m = archived_morning(); original = deepcopy(m)
    result = forecast_center_construction_provenance(m)
    assert result['status'] == 'ARITHMETIC_VERIFIED_SOURCE_UNVERIFIED'
    assert result['selected_path'] == 'STRADDLE_FIRST'
    assert result['forecast_center'] == 100
    assert result['provider_source_verified'] is False
    assert result['source_quote_timestamp'] is None
    assert m == original


def test_frozen_provenance_mismatch_not_silently_repaired():
    m = archived_morning()
    m['structured']['forecast_provenance_diagnostics']['expected_move']['upper'] = 120
    assert forecast_center_construction_provenance(m)['status'] == 'INCONSISTENT'
    assert shadow_directional_center_sensitivity(m)['status'] == 'ABSTAIN'


def test_absent_provenance_no_hindsight_reconstruction():
    m = morning()
    result = forecast_center_construction_provenance(m)
    assert result['status'] == 'UNVERIFIABLE'
    assert shadow_directional_center_sensitivity(m, actual_low=1., actual_high=10000.)['candidates'] == []


def test_fixed_sensitivity_is_frozen_only_and_width_constant():
    m = archived_morning(); old = deepcopy(m)
    plain = shadow_directional_center_sensitivity(m)
    scored = shadow_directional_center_sensitivity(m, actual_low=96., actual_high=106.)
    assert plain['status'] == 'DESCRIPTIVE_ONLY'
    assert len(plain['candidates']) == 2
    assert all('retrospective_abs_center_error' not in x for x in plain['candidates'])
    assert all(x['width_unchanged'] for x in scored['candidates'])
    assert [x['offset_points'] for x in plain['candidates']] == [x['offset_points'] for x in scored['candidates']]
    assert all('retrospective_abs_center_error' in x for x in scored['candidates'])
    assert m == old


def test_future_feature_timestamp_abstains():
    m = archived_morning()
    m['structured']['premarket_directional_feature_snapshot']['features']['overnight_es_return']['observed_at'] = '2026-11-03T20:00:00-05:00'
    assert shadow_directional_center_sensitivity(m)['status'] == 'ABSTAIN'


def test_completed_outcome_is_linked_but_not_required_for_construction():
    m = archived_morning(); r = recap()
    result = shadow_outcome_attribution({DAY: m}, [r]); assert result['eligible_sessions'] == 1
    row = result['rows'][0]
    assert row['forecast_center_construction_provenance']['status'] == 'ARITHMETIC_VERIFIED_SOURCE_UNVERIFIED'
    assert row['shadow_directional_center_sensitivity']['status'] == 'DESCRIPTIVE_ONLY'
    assert result['comparison_ready'] is False
    assert result['production_promotion'] is False
