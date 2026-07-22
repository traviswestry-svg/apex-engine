from engine.trade_director_options_intelligence import build_options_intelligence


def _ctx(strategy='LONG_CALL'):
    return {'strategy_orchestration': {'selected_strategy': {'strategy': strategy, 'score': 82}, 'market_inputs': {'regime': 'TREND_CONTINUATION'}}, 'current_price': 6000}


def test_chain_required_does_not_fabricate_contract():
    out = build_options_intelligence(_ctx(), [])
    assert out['decision_gate'] == 'CHAIN_REQUIRED'
    assert out['best_contract'] is None
    assert out['execution_contract']['executable'] is False


def test_liquid_compatible_contract_is_selected():
    rows = [{'osi_key':'SPXW TEST','side':'CALL','strike':6005,'expiration':'2026-07-22','bid':10,'ask':10.4,'delta':.51,'gamma':.02,'theta':-.8,'vega':.1,'volume':900,'open_interest':2500}]
    out = build_options_intelligence(_ctx(), rows)
    assert out['decision_gate'] == 'CONTRACT_CANDIDATE_SELECTED'
    assert out['best_contract']['symbol'] == 'SPXW TEST'


def test_wrong_side_and_bad_quote_rejected():
    rows = [{'osi_key':'BAD','side':'PUT','strike':6005,'expiration':'2026-07-22','bid':1,'ask':2,'delta':.5,'volume':0,'open_interest':0}]
    out = build_options_intelligence(_ctx(), rows)
    assert out['decision_gate'] == 'NO_ELIGIBLE_CONTRACT'
    assert out['best_contract'] is None


def test_stand_down_remains_authoritative():
    rows = [{'osi_key':'SPXW TEST','side':'CALL','strike':6005,'expiration':'2026-07-22','bid':10,'ask':10.2,'delta':.5,'volume':900,'open_interest':2500}]
    out = build_options_intelligence(_ctx('STAND_DOWN'), rows)
    assert out['decision_gate'] == 'STAND_DOWN'
