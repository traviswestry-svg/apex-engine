from engine.regime_forecast_integrity import diagnose


def recap(day, label='Balanced Auction', actual='Trend'):
    return {'session_date': day, 'forecast_id': 'fcst_' + day,
            'forecast_snapshot_hash': 'hash_' + day,
            'comparison': {'actual': {'available': True, 'low': 100, 'high': 120},
                           'projected_regime': label, 'actual_regime': actual,
                           'checks': [{'key': 'expected_move_containment', 'projected': '90 to 130'},
                                      {'key': 'expected_move_size', 'projected': 20,
                                       'actual': 20, 'reference_spot': 110,
                                       'actual_metric': 'MAX_ABS_EXCURSION_FROM_FROZEN_MORNING_SPOT'}]}}


def test_missing_archive_is_unverifiable_not_fallback():
    report = diagnose([recap('2026-10-01')], exploratory_min_train=2)
    assert report['all_same_projected_regime']
    assert report['regime_source_counts'] == {'MORNING_ARCHIVE_UNAVAILABLE': 1}
    assert report['production_promotion'] is False


def test_identity_match_proves_reference_and_source():
    r = recap('2026-10-01')
    morning = {'canonical_forecast_provenance': {'forecast_id': r['forecast_id'],
                                                 'snapshot_hash': r['forecast_snapshot_hash']},
               'structured': {'spot': 110, 'forecast_regime_source': 'DETERMINISTIC_ACTIVE_TRADE_MAP_CONSENSUS',
                              'forecast_regime_confidence': 0.75}}
    report = diagnose([r], {'2026-10-01': morning}, exploratory_min_train=2)
    assert report['reference_integrity_counts'] == {'MATCH': 1}
    assert report['regime_source_counts'] == {'DETERMINISTIC_ACTIVE_TRADE_MAP_CONSENSUS': 1}


def test_mismatch_never_trusts_morning_source():
    r = recap('2026-10-01')
    morning = {'canonical_forecast_provenance': {'forecast_id': 'wrong', 'snapshot_hash': 'wrong'},
               'structured': {'spot': 110, 'forecast_regime_source': 'SOME_SOURCE'}}
    report = diagnose([r], {'2026-10-01': morning}, exploratory_min_train=2)
    assert report['regime_source_counts'] == {'ARCHIVE_IDENTITY_MISMATCH': 1}
    assert report['reference_integrity_counts'] == {'UNVERIFIED_ARCHIVE_IDENTITY': 1}
