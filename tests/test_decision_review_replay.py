import os
from engine import recommendation_ledger as ledger
from engine.decision_review import build_decision_review, build_replay, record_decision_snapshot


def _capture():
    return {
        'recommendation_id': 'rec-test-113', 'idempotency_key': 'idem-test-113', 'captured_at': '2026-07-18T14:00:00+00:00',
        'session_date': '2026-07-18', 'ticker': 'SPX', 'strategy': 'NO_TRADE', 'state': 'OBSERVED', 'tradeable': False,
        'raw_confidence': 0, 'final_live_confidence': 0, 'legs': {}, 'evidence': {'why': 'test'}, 'probability': {},
        'confirmation': {}, 'snapshot': {}, 'feature_hash': 'abc', 'ledger_schema_version': 1, 'application_version': 'test',
    }


def test_review_and_replay_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv('RECOMMENDATION_LEDGER_DB_PATH', str(tmp_path / 'ledger.db'))
    ledger.record_recommendation(_capture())
    state = {'market_state': {'price': 6000, 'flow_bias': 'BULLISH'}, 'institutional_intelligence': {'institutional_bias': 'BULLISH', 'confidence': 70}, 'session': 'MARKET_OPEN'}
    result = record_decision_snapshot('rec-test-113', state)
    assert 'STATE_CHANGE' in result['events_created']
    review = build_decision_review('rec-test-113')
    replay = build_replay('rec-test-113')
    assert review['outcome_status'] == 'UNRESOLVED'
    assert review['historical_performance_claimed'] is False
    assert replay['status'] == 'AVAILABLE'
    assert any(f['type'] == 'NARRATIVE_SNAPSHOT' for f in replay['frames'])
