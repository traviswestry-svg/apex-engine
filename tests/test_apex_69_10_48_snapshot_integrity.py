from engine.morning_forecast_integrity import snapshot_identity, narrative_consistency, quality_dimensions


def test_identity_changes_with_levels():
    a = {'levels': [{'name': 'Call Wall', 'price': 7800}]}
    b = {'levels': [{'name': 'Call Wall', 'price': 8000}]}
    assert snapshot_identity(a, '2026-10-27', 'PREMARKET') != snapshot_identity(b, '2026-10-27', 'PREMARKET')
    assert snapshot_identity(a, '2026-10-27', 'PREMARKET') == snapshot_identity(a, '2026-10-27', 'PREMARKET')


def test_narrative_detects_conflicting_wall_and_poc():
    structured = {'levels': [{'name': 'Call Wall', 'price': 7800}, {'name': 'Developing POC', 'price': 7671}]}
    result = narrative_consistency('Call wall (8000.0), developing POC (7674.0)', structured)
    assert result['status'] == 'MISMATCH'
    assert len(result['mismatches']) == 2


def test_missing_narrative_is_not_certified():
    assert narrative_consistency('', {'levels': []})['status'] == 'NOT_VERIFIABLE'
    q = quality_dimensions(narrative_status='ASYNC_PENDING', snapshot_check={'status': 'NOT_VERIFIABLE'})
    assert q['calendar_coverage'] == 'NOT_VERIFIED'
    assert q['forecast_confidence'] == 'NOT_HISTORICALLY_CALIBRATED'
