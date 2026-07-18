from engine.institutional_narrative import build_consensus_gauge, build_conviction, build_institutional_narrative
from engine.institutional_decision_object import build_canonical_institutional_decision


def live_state():
    return {
        'market_state': {'price': 6000, 'regime': 'TREND', 'flow_bias': 'BULLISH', 'vah': 6005, 'val': 5980, 'poc': 5995},
        'institutional_intelligence': {'institutional_bias': 'BULLISH', 'confidence': 82, 'primary_thesis': 'Acceptance above value favors continuation.'},
        'dealer_positioning': {'delta': {'bias': 'BUYING'}},
        'market_drivers': {'breadth': 'BULLISH'},
        'confirmation': {'bias': 'BULLISH'},
        'session': 'MARKET_OPEN',
    }


def test_consensus_and_conviction_are_deterministic():
    c = build_consensus_gauge(live_state())
    v = build_conviction(live_state(), c)
    assert c['direction'] == 'BULLISH'
    assert c['score'] > 50
    assert v['score'] > 50
    assert v['historical_calibration_applied'] is False


def test_narrative_live_and_fail_closed():
    n = build_institutional_narrative(live_state())
    assert n['status'] == 'LIVE'
    assert n['trade_guidance_enabled'] is True
    degraded = build_institutional_narrative({}, session_state='MARKET_OPEN')
    assert degraded['status'] == 'DEGRADED'
    assert degraded['trade_guidance_enabled'] is False
    assert degraded['primary_thesis'] == 'NO_LIVE_THESIS'


def test_closed_state_disables_guidance():
    n = build_institutional_narrative(live_state(), session_state='MARKET_CLOSED')
    assert n['status'] == 'CLOSED'
    assert n['trade_guidance_enabled'] is False


def test_canonical_decision_fails_closed_without_data():
    obj = build_canonical_institutional_decision({})
    assert obj['decision_state'] == 'NO_TRADE'
    assert obj['fail_closed'] is True
    assert obj['historical_performance_claimed'] is False
