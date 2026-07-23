from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_phase34_progression_and_quality_gate(tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_GOVERNANCE_DB', str(tmp_path/'g.db'))
    import engine.trade_director_session_allocation as e
    d=e.build_session_allocation(environment_quality='HIGH_QUALITY', session_date='2026-07-23')
    assert d['max_trades']==5 and d['sequence']==[1,3,4,3,3]
    assert d['recommended_contracts']==1
    e.record_confirmed_trade(ticker='SPX',side='CALL',quantity=1,session_date='2026-07-23',created_at='2026-07-23T09:40:00')
    d=e.build_session_allocation(environment_quality='FAVORABLE', session_date='2026-07-23')
    assert d['next_trade_number']==2 and d['recommended_contracts']==3

def test_four_contract_tier_requires_high_quality(tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_GOVERNANCE_DB', str(tmp_path/'g.db'))
    import engine.trade_director_session_allocation as e
    for i,q in enumerate((1,3)):
        e.record_confirmed_trade(ticker='SPX',side='CALL',quantity=q,session_date='2026-07-23',created_at=f'2026-07-23T09:4{i}:00')
    assert e.build_session_allocation(environment_quality='FAVORABLE',session_date='2026-07-23')['recommended_contracts']==3
    assert e.build_session_allocation(environment_quality='HIGH_QUALITY',session_date='2026-07-23')['recommended_contracts']==4

def test_daily_limit_and_loss_lockout(tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_GOVERNANCE_DB', str(tmp_path/'g.db'))
    import engine.trade_director_session_allocation as e
    d=e.build_session_allocation(environment_quality='HIGH_QUALITY',consecutive_losses=2,session_date='2026-07-23')
    assert d['recommended_contracts']==0 and d['allocation_gate']=='LOSS_LOCKOUT'

def test_assistant_restores_market_director_to_top_and_adds_allocation_panel():
    html=(ROOT/'templates/assistant.html').read_text()
    assert html.index('id="app"') < html.index('Manual Trade Confirmation')
    assert 'id="sessionAllocation"' in html
    assert 'Session Allocation & Risk Plan' in html

def test_phase34_routes_and_confirmation_gate_present():
    app=(ROOT/'app.py').read_text()
    assert '/api/session-allocation' in app
    assert 'td34_record_confirmed_trade' in app
    html=(ROOT/'templates/assistant.html').read_text()
    assert 'never places, modifies, or authorizes an order' in html
