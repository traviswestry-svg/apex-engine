from engine import adaptive_trade_management as atm

def snap(progress_mark=11, valid=True):
    return {'position':{'position_open':True,'trade_id':'T1','symbol':'SPX','side':'LONG','quantity':1,'entry_price':10,'mark_price':progress_mark,'stop_price':9,'tp1':11,'tp2':12},'institutional_confluence_score':85,'institutional_pressure_score':82,'pressure_conviction':80,'market_state_confidence':88,'playbook_quality_score':90,'structure_alignment':84,'playbook_valid':valid,'market_state_valid':True}

def test_one_r_recommends_protection():
    x=atm.evaluate(snap(11)); assert x['action']=='PROTECT' and any(r['type']=='BREAKEVEN' for r in x['recommendations'])

def test_invalidation_recommends_exit():
    x=atm.evaluate(snap(10.5,False)); assert x['action']=='EXIT' and x['urgency']=='HIGH'

def test_never_mutates_orders():
    x=atm.evaluate(snap()); assert x['advisory_only'] and x['broker_effect']=='NONE' and not x['orders_changed']

def test_immutable_record(tmp_path,monkeypatch):
    from engine import institutional_governance as gov
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'g.db'))
    a=atm.record(snap(),trade_id='T1',observed_at='2026-07-18T14:00:00+00:00'); b=atm.record(snap(),trade_id='T1',observed_at='2026-07-18T14:00:00+00:00')
    assert a['created'] and not b['created'] and b['status']=='IMMUTABLE_EXISTS'

def test_routes_present():
    from pathlib import Path
    s=(Path(__file__).parents[1]/'engine/institutional_roadmap_routes.py').read_text()
    assert '/api/trade-management/evaluate' in s and '/api/trade-management/record' in s
