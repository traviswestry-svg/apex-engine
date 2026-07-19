from engine.institutional_intelligence_engine import (
    VERSION, build_expected_move_intelligence, build_institutional_intelligence_v19,
    build_overnight_structure, build_volume_transition_intelligence,
)

def sample():
    return {
        'ticker':'SPX','data_fresh':True,
        'market_state':{'price':6000,'poc_migration':'RISING','data_fresh':True,'overnight_high':5995,'overnight_low':5970,'previous_day_high':6010,'previous_day_low':5960},
        'volume_profile':{'profile':[{'price':5996,'volume':100},{'price':5998,'volume':20},{'price':6000,'volume':18},{'price':6002,'volume':60},{'price':6004,'volume':100}]},
        'options_chain':{'expected_move_points':35},
        'auction_intelligence':{'auction_state':{'state':'TREND_UP','confidence':75}},
        'dealer_positioning':{'delta':{'bias':'BUYING'},'gamma':{'regime':'NEGATIVE_GAMMA'}},
        'flow_intelligence':{'flow_bias':'BULLISH','flow_conviction':80},
        'institutional_intelligence':{'institutional_bias':'BULLISH','confidence':75},
    }

def test_volume_transition_colors_and_no_secrets():
    out=build_volume_transition_intelligence(sample()['volume_profile'],6000)
    assert out['available'] is True
    assert {x['display_color'] for x in out['levels']} <= {'GREEN','RED','NEUTRAL'}
    assert 'api_key' not in str(out).lower()

def test_expected_move():
    out=build_expected_move_intelligence(sample())
    assert out['upper']==6035 and out['lower']==5965

def test_overnight_structure():
    out=build_overnight_structure(sample())
    assert out['location']=='ABOVE_ONH' and out['signal']=='BULLISH'

def test_unified_engine_is_advisory_and_bullish():
    out=build_institutional_intelligence_v19(sample())
    assert out['version']==VERSION
    assert out['bias']=='BULLISH'
    assert out['guardrails']['broker_mutation'] is False
    assert out['guardrails']['automatic_execution'] is False

def test_stale_data_not_execution_eligible():
    data=sample(); data['data_fresh']=False; data['market_state']['data_fresh']=False
    out=build_institutional_intelligence_v19(data)
    assert out['execution_eligible'] is False
    assert 'STALE_DATA' in out['quality_flags']

def test_missing_inputs_fail_closed():
    out=build_institutional_intelligence_v19({})
    assert out['execution_eligible'] is False
    assert 'LOW_INPUT_COVERAGE' in out['quality_flags']
