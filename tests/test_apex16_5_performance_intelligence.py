import tempfile
from engine import performance_intelligence as pi
from engine import institutional_governance as gov

def sample():
    return [
      {'trade_id':'a','symbol':'SPX','opened_at':'2026-07-13T09:40:00-04:00','closed_at':'2026-07-13T09:48:00-04:00','net_pnl':500,'realized_r':1.5,'market_state':'TREND_AUCTION','playbook':'OPENING_DRIVE','volatility_regime':'EXPANSION','gamma_regime':'NEGATIVE','alpha_source':'FLOW'},
      {'trade_id':'b','symbol':'SPX','opened_at':'2026-07-14T09:50:00-04:00','closed_at':'2026-07-14T10:00:00-04:00','net_pnl':400,'realized_r':1.2,'market_state':'TREND_AUCTION','playbook':'OPENING_DRIVE','volatility_regime':'EXPANSION','gamma_regime':'NEGATIVE','alpha_source':'FLOW'},
      {'trade_id':'c','symbol':'SPX','opened_at':'2026-07-15T12:00:00-04:00','closed_at':'2026-07-15T12:12:00-04:00','net_pnl':-300,'realized_r':-1,'market_state':'BALANCED_AUCTION','playbook':'FAILED_BREAKOUT','volatility_regime':'COMPRESSION','gamma_regime':'POSITIVE','loss_reason':'CHOP'},
    ]

def test_deterministic_analysis_and_dimensions():
    a=pi.analyze(sample(),minimum_sample=1); b=pi.analyze(sample(),minimum_sample=1)
    assert a==b and a['overall']['net_pnl']==600
    assert a['breakdowns']['market_state'][0]['value']=='TREND_AUCTION'

def test_coaching_is_descriptive_only():
    out=pi.analyze(sample(),minimum_sample=1)
    assert out['descriptive_only'] and out['production_effect']=='NONE'
    assert out['automatic_policy_update_enabled'] is False

def test_immutable_observation(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix='.db') as f:
        monkeypatch.setattr(gov,'DB_PATH',f.name)
        one=pi.record_observation(sample()[0]); two=pi.record_observation(sample()[0])
        assert one['created'] is True and two['status']=='IMMUTABLE_EXISTS'

def test_status_safety(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix='.db') as f:
        monkeypatch.setattr(gov,'DB_PATH',f.name)
        s=pi.status(); assert not s['recommendation_mutation_enabled'] and not s['broker_order_submission_enabled']

def test_entry_window_and_weekday():
    x=pi.normalize_trade(sample()[0]); assert x['dimensions']['ENTRY_WINDOW'.lower()]=='OPENING_0930_0945'; assert x['dimensions']['weekday']=='MONDAY'
