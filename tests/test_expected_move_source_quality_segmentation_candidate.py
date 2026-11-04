"""Research-only source eligibility / outcome stratification regression coverage."""
from copy import deepcopy
from engine.premarket_directional_features import (
    expected_move_source_eligibility, source_quality_coverage, shadow_outcome_attribution,
    archive_diagnostics,
)
from test_premarket_magnitude_conflict_outcome_candidate import DAY, AT, morning, recap


def with_audit(status='SOURCE_VERIFIED', verified=True, issues=None, *, iv=None):
    m = morning()
    frozen = {
        'schema': 'EXPECTED_MOVE_DECISION_TIME_SOURCE_INTEGRITY_V1',
        'status': status, 'provider_source_verified': verified,
        'issues': [] if issues is None else issues,
        'decision_at': AT, 'option_expiration': '2026-11-03',
        'limits': {'max_quote_age_seconds': 120},
        'quote_legs': {side: {'ask': 11., 'bid': 9., 'mid': 10., 'method': 'mid',
                             'contract_id': side, 'source': 'polygon', 'expiration': '2026-11-03',
                             'quote_age_at_decision_seconds': 15.,
                             'provider_quote_timestamp': '2026-11-03T11:17:57+00:00'}
                       for side in ('call', 'put')},
    }
    if iv is not None:
        frozen['source_atm_iv'] = iv
    m['structured']['forecast_provenance_diagnostics'] = {'expected_move': {
        'reference_spot': 100.0, 'upper': 110.0, 'lower': 90.0,
        'selected_one_sigma': 10.0, 'straddle_implied_one_sigma': 10.0,
        'selected_path': 'STRADDLE_FIRST',
        'decision_time_source_integrity': frozen,
    }}
    m['structured']['expected_move']['one_sigma'] = 10.0
    if iv is not None:
        m['structured']['forecast_provenance_diagnostics']['expected_move']['iv_implied_one_sigma'] = 11.0
    return m


def test_strict_requires_consistent_frozen_audit_and_construction():
    m = with_audit()
    original = deepcopy(m)
    result = expected_move_source_eligibility(m)
    assert result['quality'] == 'VERIFIED'
    assert result['strict_research_eligible'] is True
    assert result['iv_alternative_evidence'] == 'NO_COMPLETE_FROZEN_IV_ALTERNATIVE'
    assert m == original
    m['structured']['forecast_provenance_diagnostics']['expected_move']['upper'] = 200
    assert expected_move_source_eligibility(m)['quality'] == 'INCONSISTENT_AUDIT'


def test_audit_label_without_valid_quote_legs_not_source_verified():
    m = with_audit()
    m['structured']['forecast_provenance_diagnostics']['expected_move']['decision_time_source_integrity']['quote_legs']['call']['bid'] = 0
    result = expected_move_source_eligibility(m)
    assert result['quality'] == 'INCONSISTENT_AUDIT'
    assert result['strict_research_eligible'] is False


def test_degraded_rejected_and_contradictory_are_not_promoted():
    samples = [
        (with_audit('DEGRADED_SOURCE_EVIDENCE', False, ['STALE_QUOTE_CALL', 'LAST_TRADE_FALLBACK_PUT']), 'DEGRADED'),
        (with_audit('REJECTED_INTEGRITY', False, ['FUTURE_QUOTE']), 'REJECTED'),
        (with_audit('SOURCE_VERIFIED', False), 'INCONSISTENT_AUDIT'),
        (with_audit('SOURCE_VERIFIED', True, ['STALE_QUOTE_CALL']), 'INCONSISTENT_AUDIT'),
        (with_audit('UNKNOWN', True), 'INCONSISTENT_AUDIT'),
        (morning(), 'LEGACY_UNVERIFIED'),
    ]
    for m, expected in samples:
        classified = expected_move_source_eligibility(m)
        assert classified['quality'] == expected
        assert classified['strict_research_eligible'] is False
    legacy = expected_move_source_eligibility(morning())
    assert legacy['frozen_integrity_status'] is None


def test_iv_alternative_does_not_claim_verified_quote_or_override_straddle():
    m = with_audit('DEGRADED_SOURCE_EVIDENCE', False, ['STALE_QUOTE_CALL'], iv=0.22)
    row = expected_move_source_eligibility(m)
    assert row['quality'] == 'DEGRADED'
    assert row['iv_alternative_evidence'] == 'NUMERIC_IV_AND_IMPLIED_MOVE_ARCHIVED_SOURCE_NOT_INDEPENDENTLY_VERIFIED'
    assert row['production_promotion'] is False
    assert m['structured']['forecast_provenance_diagnostics']['expected_move']['selected_path'] == 'STRADDLE_FIRST'


def test_coverage_excludes_noncanonical_origins_and_counts_legacy():
    origin = with_audit()
    bad = deepcopy(origin)
    bad['session_context']['brief_mode'] = 'NEXT_SESSION_PREP'
    result = source_quality_coverage({DAY: origin, '2026-11-02': bad,
                                      '2026-11-04': morning(generated='2026-11-04T06:00:00-05:00')})
    assert result['eligible_canonical_origins'] == 2
    assert result['quality_counts'] == {'VERIFIED': 1, 'LEGACY_UNVERIFIED': 1}
    assert result['source_verified_fraction'] == 0.5
    assert result['excluded_origins']['INVALID_CANONICAL_ORIGIN'] == 1


def test_strict_outcome_denominator_excludes_degraded_but_keeps_descriptive_row():
    degraded = with_audit('DEGRADED_SOURCE_EVIDENCE', False, ['STALE_QUOTE_CALL'])
    orig = deepcopy(degraded)
    rr = recap()
    result = shadow_outcome_attribution({DAY: degraded}, [rr], min_samples=2)
    assert result['eligible_sessions'] == 1
    assert len(result['rows']) == 1
    assert result['rows'][0]['expected_move_source_eligibility']['quality'] == 'DEGRADED'
    assert result['source_quality_segmentation']['groups']['DEGRADED']['sessions'] == 1
    assert result['source_quality_segmentation']['strict_verified_sessions'] == 0
    assert result['comparison_ready'] is False
    assert result['accuracy_claim'] is False
    assert degraded == orig


def test_verified_cohort_only_counts_exact_completed_rows():
    m = with_audit()
    r = recap(actual_low=96, actual_high=106)
    output = shadow_outcome_attribution({DAY: m}, [r])
    g = output['source_quality_segmentation']['groups']['VERIFIED']
    assert g['sessions'] == 1 and g['contained_sessions'] == 1
    assert g['mean_absolute_center_residual_points'] == 1.0
    assert output['comparison_ready'] is False
    assert output['source_quality_segmentation']['strict_comparison_ready'] is False
    assert output['rows'][0]['expected_move_source_eligibility']['strict_research_eligible'] is True
    assert shadow_outcome_attribution({DAY: m}, [recap(forecast_id='wrong')])['source_quality_segmentation']['strict_verified_sessions'] == 0


def test_archive_diagnostics_exposes_quality_without_looking_up_actual_outcomes():
    m = with_audit('REJECTED_INTEGRITY', False, ['FUTURE_QUOTE'])
    a = archive_diagnostics({DAY: m})
    assert a['details'][0]['expected_move_source_eligibility']['quality'] == 'REJECTED'
    assert 'forecast_center_residual_points' not in a['details'][0]
    assert 'source_quality_coverage' not in a  # persistence reader owns cohort coverage
