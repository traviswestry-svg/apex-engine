from engine.institutional_market_structure_engine import (
    VERSION, build_acceptance_rejection, build_auction_defects,
    build_day_type_probability, build_institutional_market_structure,
    build_multi_timeframe_profiles, build_opening_type, build_poc_value_migration,
)

def profile(poc=6000,vah=6005,val=5995):
    return {'available':True,'levels':{'poc':poc,'vah':vah,'val':val,'hvn':[poc,poc+2],'lvn':[val+1,vah-1]},'profile':[{'price':p,'activity':100-abs(p-poc)*8} for p in range(int(val),int(vah)+1)]}

def sample():
    bars=[]
    px=6001
    for i in range(10):
        bars.append({'open':px+i*.8,'high':px+i*.8+2,'low':px+i*.8-.5,'close':px+i*.8+1.5,'volume':100+i*10})
    return {'ticker':'SPX','data_fresh':True,'market_state':{'price':6009.5,'session_open':6001,'session_high':6011,'session_low':6000.5,'atr':15,'data_fresh':True,'previous_day_high':6015,'previous_day_low':5980,'overnight_high':6007,'overnight_low':5990},'volume_profile':profile(6005,6008,6001),'previous_day_profile':profile(5997,6002,5992),'volume_profile_5m':profile(6004,6008,6000),'volume_profile_15m':profile(6003,6007,5999),'bars':bars}

def test_multi_timeframe_and_confluence():
    out=build_multi_timeframe_profiles(sample())
    assert out['available'] and out['available_count'] >= 3
    assert out['confluence_levels']

def test_poc_and_value_migration_rising():
    out=build_poc_value_migration(sample())
    assert out['poc_direction']=='RISING'
    assert out['institutional_read']=='ACCEPTANCE_HIGHER'

def test_opening_type_classified():
    out=build_opening_type(sample())
    assert out['available'] and out['type'].startswith('OPEN_')

def test_auction_defects_are_structured():
    out=build_auction_defects(sample())
    assert out['available']
    assert isinstance(out['single_prints'],list)
    assert 'auction_complete_high' in out

def test_acceptance_and_day_type():
    data=sample(); mtf=build_multi_timeframe_profiles(data)
    acceptance=build_acceptance_rejection(data,mtf)
    migration=build_poc_value_migration(data,mtf); opening=build_opening_type(data,mtf)
    day=build_day_type_probability(data,migration,opening,acceptance)
    assert acceptance['available']
    assert day['trend_day_probability'] + day['balance_day_probability'] == 100

def test_full_engine_read_only_and_targets():
    out=build_institutional_market_structure(sample())
    assert out['version']==VERSION and out['state']=='READY'
    assert out['guardrails']['broker_mutation'] is False
    assert out['structure_levels']['targets']['upside']
    assert 'api_key' not in str(out).lower()

def test_stale_data_is_flagged():
    data=sample(); data['data_fresh']=False; data['market_state']['data_fresh']=False
    out=build_institutional_market_structure(data)
    assert 'STALE_DATA' in out['warnings']
    assert out['guardrails']['stale_data_blocks_use'] is True

def test_missing_data_degrades_safely():
    out=build_institutional_market_structure({})
    assert out['state']=='DEGRADED'
    assert out['guardrails']['broker_mutation'] is False
