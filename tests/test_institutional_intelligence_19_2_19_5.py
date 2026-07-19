import json
from engine.institutional_dealer_positioning_engine import build_dealer_positioning
from engine.institutional_options_flow_engine import build_options_flow_intelligence
from engine.institutional_probability_engine import build_probability_engine
from engine.adaptive_learning_engine_v2 import build_adaptive_learning_v2
from engine.institutional_market_structure_engine import build_institutional_market_structure

def sample():
    return {'ticker':'SPX','data_fresh':True,'market_state':{'price':6000,'previous_day_high':6010,'previous_day_low':5975,'overnight_high':6005,'overnight_low':5985,'session_high':6004,'session_low':5990,'atr':22,'trend':'UP'},'dealer_positioning':{'gamma_flip':5995,'call_wall':6020,'put_wall':5960,'net_gex':-100,'dealer_delta':50,'vanna':10,'charm':5},'flow_tape':[{'side':'CALL','type':'SWEEP','premium':400000,'opening':True,'repeat_count':4,'at_ask':True},{'side':'PUT','type':'BLOCK','premium':100000,'opening':False,'at_bid':True}], 'recommendation_history':[{'outcome':'WIN','setup':'ORB','regime':'TREND','hour':'10'} for _ in range(25)]+[{'outcome':'LOSS','setup':'FADE','regime':'RANGE','hour':'11'} for _ in range(10)]+[{'outcome':'NOT_EXECUTABLE','setup':'ORB'}]}

def test_dealer_engine_core_levels_and_regime():
    x=build_dealer_positioning(sample()); assert x['available']; assert x['gamma_flip']==5995; assert x['gamma_regime']=='NEGATIVE_GAMMA'; assert x['guardrails']['broker_mutation'] is False

def test_dealer_sandbox_has_no_secret_leak():
    x=sample(); x['dealer_positioning']['api_key']='secret-value'; out=json.dumps(build_dealer_positioning(x)); assert 'secret-value' not in out and 'api_key' not in out

def test_flow_quality_clustering_and_bias():
    x=build_options_flow_intelligence(sample()); assert x['event_count']==2; assert x['institutional_clusters']==1; assert x['bias']=='BULLISH'; assert x['events'][0]['quality']>=70

def test_flow_empty_degrades_safely():
    x=sample(); x.pop('flow_tape'); out=build_options_flow_intelligence(x); assert out['state']=='DEGRADED'; assert out['guardrails']['broker_mutation'] is False

def test_probability_outputs_sum_and_bounds():
    x=sample(); d=build_dealer_positioning(x); f=build_options_flow_intelligence(x); p=build_probability_engine(x,d,f,{})
    assert p['directional']['bullish']+p['directional']['bearish']==100
    for k in ('new_daily_high_probability','new_daily_low_probability','break_overnight_high_probability','break_overnight_low_probability'): assert 5<=p[k]<=95

def test_probability_stale_data_warning():
    x=sample(); x['data_fresh']=False; out=build_probability_engine(x); assert 'STALE_DATA' in out['warnings']; assert out['guardrails']['stale_data_blocks_execution_use']

def test_learning_excludes_not_executable_and_does_not_apply_weights():
    out=build_adaptive_learning_v2(sample()); assert out['sample_size']==35; assert out['calibration']['not_executable_excluded']; assert out['guardrails']['automatic_weight_changes'] is False; assert all(not x['applied'] for x in out['weight_suggestions'])

def test_learning_minimum_sample_readiness():
    out=build_adaptive_learning_v2({},[{'outcome':'WIN'}]*5); assert out['learning_readiness']=='COLLECTING_DATA'

def test_all_engines_are_read_only():
    x=sample(); engines=[build_dealer_positioning(x),build_options_flow_intelligence(x),build_probability_engine(x),build_adaptive_learning_v2(x)]
    assert all(e['guardrails']['broker_mutation'] is False for e in engines)
