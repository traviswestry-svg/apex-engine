from engine.decision_reasoning_contracts import build_engine_opinions, build_correlation_aware_consensus
from engine.institutional_narrative import build_institutional_narrative
from engine.institutional_decision_object import build_canonical_institutional_decision


def _by_name(opinions):
    return {x['engine_name']: x for x in opinions}


def test_zero_evidence_is_unknown_not_neutral_and_unavailable():
    opinions = build_engine_opinions({})
    c = build_correlation_aware_consensus(opinions)
    assert c['dominant_direction'] == 'UNKNOWN'
    assert c['direction'] == 'UNKNOWN'
    assert c['eligible_count'] == 0
    assert c['status'] == 'UNAVAILABLE'
    assert set(c['unavailable_engines']) == {
        'institutional_intelligence','auction','structure','flow',
        'liquidity','dealer','breadth','execution'
    }
    assert all(x['freshness_state'] == 'UNAVAILABLE' for x in opinions)


def test_production_schema_adapters_consume_existing_shapes():
    last = {
        'institutional_intelligence': {'available': True, 'institutional_bias': 'BULLISH', 'overall_score': 78, 'version': '7.0'},
        'auction_intelligence': {'available': True, 'auction_state': {'state': 'TREND_UP', 'confidence': 74}},
        'institutional_market_structure': {'available': True, 'direction': 'BULLISH', 'confidence': 72},
        'flow_intelligence_2': {'available': True, 'flow_bias': 'BULLISH', 'flow_conviction': 81, 'version': '3.0'},
        'liquidity_intelligence': {'ok': True, 'status': 'READY', 'institutional_intent': {'direction': 'BULLISH', 'confidence': 76}},
        'dealer_positioning': {'available': True, 'bias': 'BULLISH', 'pressure_score': 70},
        'market_drivers': {'available': True, 'market_bias': 'BULLISH', 'breadth': 'BROAD_BULLISH', 'driver_score': 73},
        'execution_intelligence': {'available': True, 'approved_side': 'CALL', 'exec_probability': 79},
    }
    ops = _by_name(build_engine_opinions(last))
    assert all(ops[k]['direction'] == 'BULLISH' for k in ops)
    assert all(ops[k]['freshness_state'] == 'CURRENT' for k in ops)
    assert ops['auction']['engine_version'] == 'UNSPECIFIED'
    assert ops['flow']['engine_version'] == '3.0'


def test_available_engine_without_direction_abstains_but_is_not_unavailable():
    ops = _by_name(build_engine_opinions({'execution_intelligence': {'available': True, 'decision_state': 'WAIT', 'exec_probability': 62}}))
    execution = ops['execution']
    assert execution['direction'] == 'ABSTAIN'
    assert execution['freshness_state'] == 'CURRENT'
    assert execution['abstain_reason'] == 'MISSING_REQUIRED_DATA'
    c = build_correlation_aware_consensus(list(ops.values()))
    assert 'execution' not in c['unavailable_engines']


def test_closed_session_falls_back_to_apex_clock_and_is_not_degraded(monkeypatch):
    import engine.live_operations as lo
    monkeypatch.setattr(lo, 'session_state', lambda *a, **k: 'MARKET_CLOSED')
    n = build_institutional_narrative({})
    assert n['market_state']['session'] == 'MARKET_CLOSED'
    assert n['data_quality']['closed'] is True
    assert n['data_quality']['status'] == 'CLOSED'
    assert n['trade_guidance_enabled'] is False
    assert n['consensus']['direction'] == 'UNKNOWN'


def test_closed_canonical_decision_reports_market_closed_and_unknown(monkeypatch):
    import engine.live_operations as lo
    monkeypatch.setattr(lo, 'session_state', lambda *a, **k: 'MARKET_CLOSED')
    d = build_canonical_institutional_decision({})
    assert d['direction'] == 'UNKNOWN'
    assert d['action'] == 'NO_TRADE'
    assert d['actionable'] is False
    assert d['status'] == 'MARKET_CLOSED'
    assert d['fail_closed'] is True


def test_known_unknowns_are_deduplicated(monkeypatch):
    import engine.live_operations as lo
    monkeypatch.setattr(lo, 'session_state', lambda *a, **k: 'MARKET_CLOSED')
    n = build_institutional_narrative({})
    values = n['thesis']['known_unknowns']
    assert len(values) == len(set(values))


def test_liquidity_race_fallback_maps_existing_leader_semantics():
    last = {'liquidity_intelligence': {'ok': True, 'status': 'READY', 'race': {'leader': 'LOWER', 'edge_pct': 20}}}
    op = _by_name(build_engine_opinions(last))['liquidity']
    assert op['direction'] == 'BEARISH'
