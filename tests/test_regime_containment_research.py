from engine.regime_containment_research import audit_archive, containment_research


def recap(day, center_shift=0, *, identity=True):
    return {
        'session_date': day, 'forecast_id': 'f-'+day if identity else None,
        'forecast_snapshot_hash': 'h-'+day,
        'comparison': {'actual': {'available': True, 'low': 90+center_shift, 'high': 110+center_shift},
            'projected_regime': 'Balanced Auction', 'actual_regime': 'Trend',
            'checks': [
                {'key': 'expected_move_containment', 'projected': '90 to 110'},
                {'key': 'expected_move_size', 'projected': 10, 'actual': 10+abs(center_shift),
                 'reference_spot': 100,
                 'actual_metric': 'MAX_ABS_EXCURSION_FROM_FROZEN_MORNING_SPOT'}]}}


def test_archive_distinguishes_missing_identity_and_vote_evidence():
    r = recap('2026-10-01')
    morning = {'canonical_forecast_provenance': {'forecast_id': r['forecast_id'],
               'snapshot_hash': r['forecast_snapshot_hash']},
               'structured': {'forecast_provenance_diagnostics': {'regime': {
                   'votes': {'Balanced Auction': 2}, 'confidence': 1,
                   'evidence_rows': [{'regime_hint': 'balance'}]}}}}
    result = audit_archive([r, recap('2026-10-02', identity=False)], {'2026-10-01': morning})
    assert result['eligible_sessions'] == 1
    assert result['excluded_sessions'] == 1
    assert result['vote_evidence_status_counts'] == {'VOTE_EVIDENCE_ARCHIVED': 1}
    assert 'MISSING_CANONICAL_FORECAST_IDENTITY' in result['excluded_details'][0]['reasons']


def test_missing_morning_not_reconstructed():
    result = audit_archive([recap('2026-10-01')], {})
    assert result['vote_evidence'][0]['vote_evidence'] is None
    assert result['vote_evidence'][0]['status'] == 'MORNING_ARCHIVE_MISSING'


def test_containment_walk_forward_is_past_only_and_non_promotable():
    dates = [f'2026-10-{d:02}' for d in range(1, 7)]
    report = containment_research([recap(d, center_shift=5) for d in dates], min_train=3)
    assert report['evaluated_sessions'] == 3
    assert report['evaluation_details'][0]['training_through'] == dates[2]
    assert report['evaluation_details'][0]['session_date'] == dates[3]
    assert report['production_promotion'] is False
    assert set(report['methods']) == {'baseline', 'center_only', 'center_and_width', 'conservative_half_width'}


def test_duplicate_date_abstains():
    records = [recap('2026-10-01'), recap('2026-10-01'), recap('2026-10-02')]
    report = containment_research(records, min_train=2)
    assert report['evaluated_sessions'] == 0
    assert audit_archive(records, {})['ambiguous_duplicate_dates'] == ['2026-10-01']
