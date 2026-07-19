import datetime as dt
from engine import live_operations as lo

def ts(seconds=0): return (dt.datetime.now(dt.timezone.utc)-dt.timedelta(seconds=seconds)).isoformat()
def healthy(): return {k:{'last_update':ts()} for k in lo.DEFAULT_THRESHOLDS}

def test_healthy_rth_is_tradeable():
    x=lo.evaluate({'session':'ACTIVE_RTH','sources':healthy()})
    assert x['tradeability']=='TRADEABLE' and x['evidence_completeness_score']==100

def test_stale_required_source_blocks():
    s=healthy(); s['options_flow']['last_update']=ts(100)
    x=lo.evaluate({'session':'ACTIVE_RTH','sources':s})
    assert x['tradeability']=='NOT_TRADEABLE'
    assert any('options_flow' in v for v in x['blocking_issues'])

def test_snapshot_drift_blocks():
    s=healthy(); s['gamma']['last_update']=ts(3)
    x=lo.evaluate({'session':'ACTIVE_RTH','sources':s,'max_snapshot_drift_seconds':1})
    assert x['tradeability']=='NOT_TRADEABLE'

def test_market_closed_is_not_failure():
    x=lo.evaluate({'session':'MARKET_CLOSED','sources':{'database':{'last_update':ts()}}})
    assert x['tradeability']=='MARKET_CLOSED'

def test_immutable_assessment():
    observed=ts(); p={'symbol':'SPX','observed_at':observed,'session':'ACTIVE_RTH','sources':healthy()}
    a=lo.record_assessment(p); b=lo.record_assessment(p)
    assert a['created'] is True and b['status']=='IMMUTABLE_EXISTS'

def test_safety_contract():
    x=lo.status(); assert x['internal_tradeability_gate_enabled'] is True
    assert x['broker_order_submission_enabled'] is False and x['recommendation_replacement_enabled'] is False
