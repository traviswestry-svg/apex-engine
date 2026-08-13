import tempfile
from engine import institutional_governance as gov
from engine import strategy_promotion_governance as spg

def setup_function(_):
    gov.DB_PATH=tempfile.mktemp(suffix='.db'); spg.init_db()

def good():
    return {'candidate':{'strategy_id':'SPX_OPEN','version':'2.0','shadow_mode_complete':True,'limited_release_complete':True,'metrics':{'sample_size':50,'shadow_sample_size':25,'win_rate':63,'average_r':0.55,'profit_factor':1.7,'max_drawdown_r':3.2,'calibration_score':78,'execution_quality_score':84,'data_integrity_score':98,'regime_coverage_count':4}}}

def test_production_candidate_when_all_gates_pass():
    assert spg.evaluate(good())['promotion_state']=='PRODUCTION_CANDIDATE'

def test_more_data_required():
    p=good(); p['candidate']['metrics']['sample_size']=5
    assert spg.evaluate(p)['promotion_state']=='MORE_DATA_REQUIRED'

def test_safety_breach_rejected():
    p=good(); p['candidate']['lookahead_bias']=True
    assert spg.evaluate(p)['promotion_state']=='REJECTED'

def test_candidate_and_decision_immutable():
    p=good(); a=spg.submit_candidate(p); b=spg.submit_candidate(p)
    assert a['created'] is True and b['status']=='IMMUTABLE_EXISTS'
    d={'candidate_id':a['candidate_id'],'observed_at':'2026-07-18T10:00:00+00:00',**p}
    x=spg.record_decision(d); y=spg.record_decision(d)
    assert x['created'] is True and y['status']=='IMMUTABLE_EXISTS'

def test_manual_approval_required_and_no_production_effect():
    p=good(); a=spg.submit_candidate(p); d=spg.record_decision({'candidate_id':a['candidate_id'],**p})
    out=spg.approve({'decision_id':d['decision_id'],'reviewer':'TRAVIS','action':'APPROVE','rationale':'validated evidence package'})
    assert out['approval_state']=='APPROVED' and out['production_effect']=='NONE'

def test_safety_contract():
    s=spg.status(); assert s['automatic_promotion_enabled'] is False and s['broker_order_submission_enabled'] is False
