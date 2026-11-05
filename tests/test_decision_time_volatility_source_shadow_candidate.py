"""Provenance / no-hindsight tests for pre-fetched ES volatility proxy."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from engine.decision_time_volatility_candidates import capture, visibility

ET = ZoneInfo('America/New_York')
DECISION = '2026-11-05T06:53:22-05:00'


def context(n=140, jump=False):
    t = datetime(2026, 11, 4, 18, tzinfo=ET).astimezone(timezone.utc)
    bars = []
    for i in range(n):
        p = 7600.0 + (i * .3) + (1.1 if i % 2 else -1.1)
        bars.append({'t': int((t + timedelta(minutes=i*5)).timestamp()*1000), 'c': p, 'v': 100})
    if jump:
        bars.append({'t': int((datetime(2026, 11, 5, 10, tzinfo=ET)).timestamp()*1000), 'c': 12000})
    return {'status': 'ok', 'ticker': 'ESZ6', 'bars': bars}


def test_completed_es_proxy_is_descriptive_only():
    ctx = context(n=153)
    row = capture(ctx, decision_at=DECISION, reference_spot=7689.4)
    c = row['candidate']
    assert c['status'] == 'DESCRIPTIVE_PROXY_AVAILABLE'
    assert c['one_sigma_spx_points'] > 0
    assert c['source_event_timestamp_verified']
    assert not c['source_is_spx_implied_volatility']
    assert not c['performance_calibrated']
    assert not row['production_promotion']


def test_no_future_bar_used_and_same_result():
    first = capture(context(153), decision_at=DECISION, reference_spot=7689.4)
    future = capture(context(153, jump=True), decision_at=DECISION, reference_spot=7689.4)
    assert first['candidate'] == future['candidate']


def test_missing_gapped_duplicate_or_stale_rejected():
    assert capture(context(10), decision_at=DECISION, reference_spot=7689.4)['candidate']['status'] == 'NOT_AVAILABLE'
    ctx = context(153); ctx['bars'][30]['t'] = ctx['bars'][29]['t']
    assert capture(ctx, decision_at=DECISION, reference_spot=7689.4)['candidate']['status'] == 'NOT_AVAILABLE'
    ctx = context(153); ctx['bars'].pop(30)
    assert capture(ctx, decision_at=DECISION, reference_spot=7689.4)['candidate']['status'] == 'NOT_AVAILABLE'
    assert capture(context(60), decision_at=DECISION, reference_spot=7689.4)['candidate']['status'] == 'NOT_AVAILABLE'


def test_bad_source_and_clock_fail_closed():
    assert capture({}, decision_at=DECISION, reference_spot=7689.4)['candidate']['status'] == 'NOT_AVAILABLE'
    assert capture(context(153), decision_at='garbage', reference_spot=7689.4)['candidate']['status'] == 'NOT_AVAILABLE'
    assert capture(context(153), decision_at=DECISION, reference_spot=None)['candidate']['status'] == 'NOT_AVAILABLE'
    assert capture(context(153), decision_at=DECISION, reference_spot=7689.4)['official_forecast_mutated'] is False


def test_visibility_no_backfill_and_no_archive_mutation():
    original = {'structured': {'forecast_provenance_diagnostics': {'expected_move': {}}}}
    assert visibility(original)['status'] == 'LEGACY_SHADOW_CANDIDATES_NOT_ARCHIVED'
    row = capture(context(153), decision_at=DECISION, reference_spot=7689.4)
    original['structured']['forecast_provenance_diagnostics']['expected_move']['shadow_volatility_source_candidates'] = row
    before = deepcopy(original)
    assert visibility(original)['frozen_candidates'] == row
    assert original == before


def test_research_reader_uses_frozen_candidate_only():
    from engine.premarket_directional_features import archive_diagnostics
    from test_premarket_magnitude_conflict_outcome_candidate import DAY, morning
    m = morning()
    old = archive_diagnostics({DAY: m})['details'][0]['decision_time_volatility_shadow_candidates']
    assert old['status'] == 'LEGACY_SHADOW_CANDIDATES_NOT_ARCHIVED'
    frozen = capture(context(153), decision_at=DECISION, reference_spot=7689.4)
    m['structured'].setdefault('forecast_provenance_diagnostics', {}).setdefault('expected_move', {})['shadow_volatility_source_candidates'] = frozen
    updated = archive_diagnostics({DAY: m})['details'][0]['decision_time_volatility_shadow_candidates']
    assert updated['frozen_candidates'] == frozen
    assert updated['status'] == 'FROZEN_SHADOW_CANDIDATES_AVAILABLE'
