from engine.morning_forecast_shadow_calibration import extract_observation, shadow_walk_forward


def recap(day, bias=10):
    date = f'2026-09-{day:02d}' if day <= 30 else f'2026-10-{day-30:02d}'
    return {'session_date': date, 'forecast_id': f'f{day}', 'forecast_snapshot_hash': f'h{day}',
            'comparison': {'actual': {'available': True, 'session_date': date, 'low': 95+bias, 'high': 105+bias},
                           'projected_regime': 'Balanced Auction', 'actual_regime': 'Mean Reversion',
                           'checks': [{'key': 'expected_move_containment', 'projected': '95.00 to 105.00'},
                                      {'key': 'expected_move_size', 'projected': 5, 'actual': 5+bias,
                                       'reference_spot': 100, 'actual_metric': 'MAX_ABS_EXCURSION_FROM_FROZEN_MORNING_SPOT'}]}}


def test_shadow_abstains_without_history():
    assert shadow_walk_forward([recap(1)] )['status'] == 'INSUFFICIENT_CHRONOLOGICAL_HISTORY'


def test_walk_forward_reduces_stable_bias_without_leakage():
    result = shadow_walk_forward([recap(d) for d in range(1, 27)], min_train=20)
    assert result['evaluated_sessions'] == 6
    assert result['shadow_center_mae'] < result['baseline_center_mae']
    assert result['shadow_move_mae'] < result['baseline_move_mae']
    assert all(x['training_through'] < x['session_date'] for x in result['evaluations'])
    assert result['production_promotion'] is False


def test_missing_provenance_or_metric_abstains():
    r = recap(1)
    del r['forecast_id']
    assert extract_observation(r) is None
    r = recap(1)
    r['comparison']['checks'][1]['actual_metric'] = 'SESSION_HIGH_LOW'
    assert extract_observation(r) is None


def test_ambiguous_duplicate_session_excluded():
    r = shadow_walk_forward([recap(1), recap(1)], min_train=2)
    assert r['eligible_sessions'] == 0
