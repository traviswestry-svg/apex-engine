"""Fail-closed premarket expected-move source research tests."""
from copy import deepcopy
from engine.premarket_expected_move_availability import capture, visibility
from engine.premarket_directional_features import archive_diagnostics, shadow_outcome_attribution
from test_premarket_magnitude_conflict_outcome_candidate import DAY, morning, recap

AT = '2026-11-04T05:42:34-05:00'
LAST = '2026-11-03T22:00:00+00:00'


def frozen_audit(*, status='DEGRADED_SOURCE_EVIDENCE', method='last_trade', quote_at=LAST, iv=None):
    legs = {k: {'provider_quote_timestamp': quote_at, 'quote_age_at_decision_seconds': 45754,
                'method': method, 'bid': 0 if method == 'last_trade' else 9,
                'ask': 0 if method == 'last_trade' else 11,
                'mid': 0 if method == 'last_trade' else 10,
                'last': 47.8 if k == 'call' else 37.6}
            for k in ('call', 'put')}
    return {'schema':'EXPECTED_MOVE_DECISION_TIME_SOURCE_INTEGRITY_V1', 'status': status,
            'quote_legs':legs, 'selected_path':'STRADDLE_FIRST',
            'source_atm_straddle_premium':85.4,'source_atm_iv':iv,
            'time_to_expiry_year_fraction':0.0011747, 'selected_one_sigma':72.59,
            'issues':['STALE_QUOTE_CALL','LAST_TRADE_FALLBACK_CALL'] if method == 'last_trade' else []}


def test_prior_session_last_trade_is_not_fresh_or_source_verified():
    src={'provider':'polygon'}
    r=capture(src, frozen_audit(), decision_at=AT, reference_spot=7568.47)
    assert r['availability']=='PRIOR_DAY_LAST_TRADE_FALLBACK_ONLY'
    assert r['regular_session_clock_context']=='OUTSIDE_US_REGULAR_SESSION_CLOCK'
    assert not r['cause_assessment']['options_trading_closed_confirmed']
    assert not r['provider_entitlement_verified']
    assert r['candidate_evidence']['prior_session_straddle']['status']=='PRIOR_DAY_LAST_TRADE_UNVERIFIED'
    assert not r['candidate_evidence']['prior_session_straddle']['allowed_as_fresh_quote']
    assert r['candidate_evidence']['iv_fallback']['status']=='NO_COMPLETE_DECISION_TIME_IV_INPUT'


def test_iv_numeric_alternative_is_never_source_verified():
    r=capture({},frozen_audit(iv=.22),decision_at=AT,reference_spot=7568.47)
    assert r['candidate_evidence']['iv_fallback']['status']=='NUMERIC_IV_AVAILABLE_SOURCE_UNVERIFIED'
    assert r['candidate_evidence']['iv_fallback']['illustrative_one_sigma'] > 0
    assert not r['candidate_evidence']['iv_fallback']['independent_provider_timestamp_verified']
    assert r['candidate_evidence']['original_selected']['method']=='STRADDLE_FIRST'


def test_missing_quote_time_does_not_fabricate_prior_snapshot():
    r=capture({},frozen_audit(quote_at=None),decision_at=AT,reference_spot=7568.47)
    assert r['availability']=='CURRENT_QUOTE_UNVERIFIED_OR_DEGRADED'
    assert r['quote_legs']['call']['provider_event_at'] is None
    assert r['candidate_evidence']['prior_session_straddle']['status']=='NOT_AVAILABLE'


def test_quote_source_verified_requires_fresh_two_sided():
    a=frozen_audit(status='SOURCE_VERIFIED',method='mid',quote_at='2026-11-04T10:42:00+00:00')
    for leg in a['quote_legs'].values():
        leg['quote_age_at_decision_seconds']=34
    r=capture({},a,decision_at=AT,reference_spot=7568.47)
    assert r['availability']=='FRESH_TWO_SIDED_SOURCE_AUDITED'
    assert r['candidate_evidence']['original_selected']['is_fresh_source_verified']


def test_verified_label_with_stale_price_does_not_upgrade():
    a=frozen_audit(status='SOURCE_VERIFIED', method='mid',quote_at=LAST)
    r=capture({},a,decision_at=AT,reference_spot=7568.47)
    assert r['availability']!='FRESH_TWO_SIDED_SOURCE_AUDITED'


def test_market_hours_does_not_claim_provider_failure_entitlement_or_closure():
    r=capture({'provider_status':'timeout'},frozen_audit(),decision_at=AT,reference_spot=7568.47)
    assert r['provider_status_as_reported']=='timeout'
    assert not r['cause_assessment']['provider_failure_confirmed']
    assert not r['cause_assessment']['entitlement_failure_confirmed']


def test_legacy_does_not_backfill_from_arithmetic_fields():
    m=morning()
    assert visibility(m)['status']=='LEGACY_AVAILABILITY_NOT_ARCHIVED'
    assert visibility(m)['frozen_availability'] is None


def test_frozen_view_is_exact_copy_and_no_outcome_leakage():
    m=morning()
    a=capture({},frozen_audit(),decision_at=AT,reference_spot=7568.47)
    m['structured'].setdefault('forecast_provenance_diagnostics', {}).setdefault('expected_move', {})['premarket_source_availability']=a
    original=deepcopy(m)
    output=visibility(m)
    assert output['frozen_availability']==a
    assert m==original
    assert 'actual_high' not in str(output)
    assert archive_diagnostics({DAY:m})['details'][0]['premarket_expected_move_source_availability']['status']=='FROZEN_AVAILABILITY_AVAILABLE'
    outcome=shadow_outcome_attribution({DAY:m},[recap()])
    assert outcome['rows'][0]['premarket_expected_move_source_availability']['frozen_availability']==a


def test_bad_time_fails_closed():
    r=capture({},frozen_audit(),decision_at='not-a-time',reference_spot=7568.47)
    assert r['regular_session_clock_context']=='DECISION_TIME_UNVERIFIABLE'
    assert r['availability']!='FRESH_TWO_SIDED_SOURCE_AUDITED'
