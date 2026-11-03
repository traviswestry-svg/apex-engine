from engine.morning_forecast_shadow_calibration import forecast_precision_report


def recap(day, bias=10, regime='Compression'):
    return {
        'session_date': f'2026-09-{day:02d}', 'forecast_id': f'fcst_{day}',
        'forecast_snapshot_hash': f'hash_{day}',
        'comparison': {
            'actual': {'available': True, 'low': 110 + bias, 'high': 150 + bias},
            'projected_regime': 'Balanced Auction', 'actual_regime': regime,
            'checks': [
                {'key': 'expected_move_containment', 'projected': '100 to 160'},
                {'key': 'expected_move_size', 'projected': 30, 'actual': 30 + bias,
                 'reference_spot': 130,
                 'actual_metric': 'MAX_ABS_EXCURSION_FROM_FROZEN_MORNING_SPOT'},
            ],
        },
    }


def test_precision_report_abstains_without_training_history():
    report = forecast_precision_report([recap(1)], min_train=2)
    assert report['production_promotion'] is False
    assert report['evaluated_sessions'] == 0
    assert report['out_of_sample']['baseline']['containment_rate'] is None


def test_precision_report_compares_same_out_of_sample_sessions():
    report = forecast_precision_report([recap(i) for i in range(1, 8)], min_train=2)
    assert report['evaluated_sessions'] == 5
    baseline = report['out_of_sample']['baseline']
    shadow = report['out_of_sample']['shadow']
    assert baseline['sessions'] == shadow['sessions'] == 5
    assert shadow['center_mae'] < baseline['center_mae']
    assert shadow['move_mae'] < baseline['move_mae']
    assert baseline['range_width_to_realized_ratio'] == 1.5
    assert report['full_archive_diagnostics']['exact_regime_accuracy'] == 0
    assert report['official_forecast_mutated'] is False


def test_precision_report_excludes_duplicate_canonical_dates():
    report = forecast_precision_report([recap(1), recap(1), recap(2)], min_train=2)
    assert report['eligible_sessions'] == 1
    assert report['evaluated_sessions'] == 0
