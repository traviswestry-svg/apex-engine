from pathlib import Path
from engine import adaptive_intelligence as ai


def test_safety_contract():
    s=ai.status(); assert s['automatic_parameter_mutation'] is False
    assert s['automatic_order_submission_enabled'] is False
    assert s['human_confirmation_required'] is True


def test_features_deterministic_and_bounded():
    a=ai._features({'regime':'TREND','vix':22,'gamma_regime':'NEGATIVE'})
    b=ai._features({'regime':'TREND','vix':22,'gamma_regime':'NEGATIVE'})
    assert a==b and all(0 <= v <= 100 for v in a.values())


def test_similarity_cosine_identity():
    x={'a':1.0,'b':2.0}; assert round(ai._cosine(x,x),6)==1.0


def test_edge_score_respects_blockers():
    out=ai.edge_score({'market_quality':95,'risk':100,'liquidity':95,'blockers':['BROKER_DRIFT']})
    assert out['institutional_edge_score'] <= 49
    assert out['trade_permission'] is False


def test_calibration_refuses_small_sample(monkeypatch):
    monkeypatch.setattr(ai,'confidence_calibration',lambda symbol='SPX':{'sample_size':5,'minimum_sample':30,'bins':[]})
    out=ai.calibrate(92); assert out['status']=='UNCALIBRATED'; assert out['calibrated_confidence']==92


def test_session_requires_real_profile():
    assert ai.record_session({'session_date':'2099-01-01'})['reason']=='PROFILE_REQUIRED'


def test_routes_are_registered():
    text=(Path(__file__).parents[1]/'engine'/'institutional_roadmap_routes.py').read_text()
    for route in ('/api/adaptive-intelligence/status','/api/adaptive-intelligence/similarity','/api/adaptive-intelligence/calibration','/api/adaptive-intelligence/playbooks','/api/adaptive-intelligence/edge'):
        assert route in text


def test_trading_desk_aggregates_adaptive_intelligence():
    text=(Path(__file__).parents[1]/'engine'/'institutional_trading_desk_ux.py').read_text()
    assert 'adaptive_intelligence' in text and 'ai18.dashboard' in text
