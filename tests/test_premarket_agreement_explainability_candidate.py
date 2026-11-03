"""Read-only explanatory diagnostics for frozen premarket shadow votes."""
from copy import deepcopy
from engine.premarket_directional_features import (
    freeze_features, shadow_direction, explain_shadow_agreement, archive_diagnostics,
)

DECISION = '2026-11-03T06:18:12-05:00'


def value_row(value):
    return {'value': value, 'source': 'ESZ6_VERIFIED_TEST',
            'observed_at': '2026-11-03T06:17:00-05:00',
            'ingested_at': '2026-11-03T06:17:15-05:00',
            'decision_time_verified': True}


def frozen(vals):
    return freeze_features({k: value_row(v) for k, v in vals.items()}, decision_at=DECISION)


def test_five_available_but_conflicting_three_causes_abstention():
    snap = frozen({'overnight_es_return': 1, 'overnight_vwap_displacement': -2,
                   'premarket_gap': 3, 'prior_day_range_position': 0.4,
                   'premarket_trend_strength': 1.2})
    before = deepcopy(snap)
    explanation = explain_shadow_agreement(snap)
    assert snap == before
    assert snap['usable_count'] == 5
    assert shadow_direction(snap)['status'] == 'ABSTAIN_INSUFFICIENT_OR_CONFLICTING_EVIDENCE'
    assert explanation['reason'] == 'REQUIRED_DIRECTIONAL_INPUTS_CONFLICT'
    assert (explanation['positive_votes'], explanation['negative_votes']) == (2, 1)
    assert explanation['features']['premarket_trend_strength']['required_for_unanimity'] is False
    assert explanation['confidence_calibrated'] is False


def test_three_agree_and_other_available_feature_disagrees_does_not_change_signal():
    snap = frozen({'overnight_es_return': -1, 'overnight_vwap_displacement': -2,
                   'premarket_gap': -3, 'premarket_trend_strength': 1})
    assert shadow_direction(snap)['direction'] == 'BEARISH'
    assert explain_shadow_agreement(snap)['reason'] == 'THREE_REQUIRED_INPUTS_UNANIMOUS'
    assert explain_shadow_agreement(snap)['negative_votes'] == 3


def test_zero_required_input_explained_without_vote():
    snap = frozen({'overnight_es_return': 0, 'overnight_vwap_displacement': 1,
                   'premarket_gap': 2})
    report = explain_shadow_agreement(snap)
    assert report['reason'] == 'REQUIRED_DIRECTIONAL_INPUT_ZERO'
    assert report['neutral_required_inputs'] == ['overnight_es_return']
    assert shadow_direction(snap)['direction'] is None


def test_missing_or_stale_required_input_explained_without_fabricating_values():
    snap = frozen({'overnight_vwap_displacement': 1, 'premarket_gap': 2,
                   'premarket_trend_strength': 4})
    snap['features']['overnight_es_return'] = {'status': 'STALE', 'value': None}
    report = explain_shadow_agreement(snap)
    assert report['reason'] == 'REQUIRED_DIRECTIONAL_INPUT_UNAVAILABLE'
    assert report['features']['overnight_es_return']['value'] is None
    assert report['features']['overnight_es_return']['status'] == 'STALE'


def test_archive_exposes_explanation_only_for_existing_frozen_snapshots():
    snap = frozen({'overnight_es_return': 1, 'overnight_vwap_displacement': -1,
                   'premarket_gap': 1})
    mornings = {'2026-11-03': {'structured': {'premarket_directional_feature_snapshot': snap}},
                '2026-10-29': {'structured': {}}}
    original = deepcopy(mornings)
    report = archive_diagnostics(mornings)
    assert mornings == original
    assert 'agreement_explainability' not in report['details'][0]
    assert report['details'][1]['agreement_explainability']['reason'] == 'REQUIRED_DIRECTIONAL_INPUTS_CONFLICT'
    assert report['official_forecast_mutated'] is False


def test_invalid_or_missing_snapshot_stays_unscored():
    result = archive_diagnostics({'2026-11-03': {'structured': {
        'premarket_directional_feature_snapshot': {'schema': 'UNKNOWN'}}}})
    assert result['details'][0]['status'] == 'UNKNOWN_SCHEMA'
    assert 'agreement_explainability' not in result['details'][0]
