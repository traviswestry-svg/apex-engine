from engine import portfolio_risk_intelligence as pri

def test_normal_portfolio_and_greeks():
    x=pri.evaluate({'account_equity':60000,'trades_today':1,'positions':[{'symbol':'SPX','quantity':1,'entry_price':10,'mark_price':11,'stop_price':9,'delta':.55,'gamma':.04,'theta':-.25,'vega':.12}]})
    assert x['risk_state']=='NORMAL' and x['net_greeks']['delta']==55 and x['total_open_risk']==100

def test_daily_loss_lockout():
    x=pri.evaluate({'realized_pnl_today':-1000,'trades_today':1})
    assert x['risk_state']=='LOCKED_OUT' and not x['permissions']['new_entries_allowed'] and x['permissions']['risk_reduction_allowed']

def test_loss_count_and_trade_frequency_lockout():
    x=pri.evaluate({'losses_today':2,'trades_today':3})
    assert x['lockout_recommended'] and 'LOSS_COUNT_LOCKOUT' in x['breaches'] and 'TRADE_FREQUENCY_LIMIT' in x['breaches']

def test_never_mutates_orders():
    x=pri.evaluate({}); assert x['advisory_only'] and x['broker_effect']=='NONE' and not x['orders_changed']

def test_immutable_record(tmp_path,monkeypatch):
    from engine import institutional_governance as gov
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'g.db'))
    a=pri.record({'account_equity':60000},observed_at='2026-07-18T15:00:00+00:00'); b=pri.record({'account_equity':60000},observed_at='2026-07-18T15:00:00+00:00')
    assert a['created'] and not b['created'] and b['status']=='IMMUTABLE_EXISTS'

def test_routes_present():
    from pathlib import Path
    s=(Path(__file__).parents[1]/'engine/institutional_roadmap_routes.py').read_text()
    assert '/api/portfolio-risk/evaluate' in s and '/api/portfolio-risk/record' in s
