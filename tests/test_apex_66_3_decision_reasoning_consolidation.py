from engine.decision_reasoning_contracts import (
    build_engine_opinions, build_correlation_aware_consensus, normalize_acceptance,
    make_engine_opinion,
)
from engine.institutional_decision_object import build_canonical_institutional_decision
from engine.institutional_narrative import build_conviction


def test_missing_data_abstains_not_neutral_or_disagreement():
    opinions = build_engine_opinions({})
    assert opinions
    assert all(o['direction'] == 'ABSTAIN' for o in opinions)
    c = build_correlation_aware_consensus(opinions)
    assert c['status'] == 'UNAVAILABLE'
    assert c['direction'] == 'NEUTRAL'
    assert c['contradicting_engines'] == []
    assert len(c['abstaining_engines']) == len(opinions)


def test_neutral_unknown_and_abstain_are_distinct():
    neutral = make_engine_opinion(engine_name='n', raw_direction='NEUTRAL', reliability=1)
    unknown = make_engine_opinion(engine_name='u', raw_direction='UNKNOWN', reliability=1)
    abstain = make_engine_opinion(engine_name='a', raw_direction=None, reliability=1, missing_data=['x'])
    assert neutral['direction'] == 'NEUTRAL' and not neutral['abstain']
    assert unknown['direction'] == 'UNKNOWN' and not unknown['abstain']
    assert abstain['direction'] == 'ABSTAIN' and abstain['abstain']


def test_same_cluster_agreement_is_decorrelated():
    ops = [
        make_engine_opinion(engine_name='institutional_intelligence', raw_direction='BULLISH', reliability=1, strength=1, correlation_cluster='STRUCTURE_AUCTION'),
        make_engine_opinion(engine_name='auction', raw_direction='BULLISH', reliability=1, strength=1, correlation_cluster='STRUCTURE_AUCTION'),
        make_engine_opinion(engine_name='structure', raw_direction='BULLISH', reliability=1, strength=1, correlation_cluster='STRUCTURE_AUCTION'),
        make_engine_opinion(engine_name='flow', raw_direction='BEARISH', reliability=1, strength=1, correlation_cluster='FLOW_LIQUIDITY'),
    ]
    c = build_correlation_aware_consensus(ops)
    assert c['raw_directional_evidence']['BULLISH'] == 3.0
    assert c['effective_directional_evidence']['BULLISH'] == 1.7
    assert c['correlation_penalty'] > 0
    assert c['redundant_evidence_score'] > 0
    assert c['direction'] == 'BULLISH'
    assert 'flow' in c['contradicting_engines']


def test_independent_contradiction_is_preserved():
    ops = [
        make_engine_opinion(engine_name='flow', raw_direction='BULLISH', reliability=1, strength=1, correlation_cluster='FLOW_LIQUIDITY'),
        make_engine_opinion(engine_name='dealer', raw_direction='BEARISH', reliability=1, strength=1, correlation_cluster='DEALER_POSITIONING'),
    ]
    c = build_correlation_aware_consensus(ops)
    assert c['direction'] == 'NEUTRAL'
    assert c['disagreement'] == 50.0
    assert len(c['active_clusters']) == 2


def test_acceptance_normalizes_existing_structure_result():
    out = normalize_acceptance({'institutional_market_structure': {'acceptance_rejection': {'state': 'ACCEPTANCE_ABOVE_VALUE', 'direction': 'BULLISH'}}})
    assert out['state'] == 'ACCEPTED'
    assert out['direction'] == 'BULLISH'
    assert out['source'] == 'institutional_market_structure.acceptance_rejection'


def test_conviction_separates_raw_and_calibrated(monkeypatch):
    # No fabricated probability even when raw conviction exists.
    state = {
        'market_state': {'price': 6000, 'flow_bias': 'BULLISH'},
        'institutional_intelligence': {'institutional_bias': 'BULLISH', 'confidence': 85},
        'dealer_positioning': {'bias': 'BULLISH'},
        'breadth': {'bias': 'BULLISH'},
        'execution_intelligence': {'approved_side': 'BULLISH', 'execution_score': 80},
    }
    v = build_conviction(state)
    assert 'raw_conviction' in v
    assert v['calibrated_conviction'] is None
    assert v['historical_calibration_applied'] is False


def test_authoritative_decision_exposes_reasoning_contracts():
    state = {
        'market_state': {'price': 6000, 'regime': 'TREND', 'flow_bias': 'BULLISH', 'session_state': 'RTH'},
        'institutional_intelligence': {'institutional_bias': 'BULLISH', 'confidence': 82, 'acceptance': 'ACCEPTING'},
        'dealer_positioning': {'bias': 'BULLISH'},
        'breadth': {'bias': 'BULLISH'},
        'confirmation': {'bias': 'BULLISH'},
        'session': 'RTH',
    }
    d = build_canonical_institutional_decision(state)
    assert d['authoritative_contract'] is True
    assert d['decision_authority'] == 'institutional_decision_object'
    assert d['schema_version'] == 'apex.institutional_decision.v3'
    assert isinstance(d['engine_opinions'], list)
    assert 'effective_consensus' in d['consensus']
    assert 'raw_conviction' in d
    assert d['calibrated_conviction'] is None
    assert 'thesis' in d and d['thesis']['state'] in {'FORMING','ACTIVE','CONFLICTED','UNKNOWN'}
    assert isinstance(d['evidence_conflict_matrix'], list)
