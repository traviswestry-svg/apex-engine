import os
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from engine.execution import traderspost_paper as tp

CLOCK = datetime(2026,10,20,14,0,tzinfo=timezone.utc)
BASE = dict(signal_id='sample-order-0001',ticker='SPX',option_type='call',action='open',
            decision_id='decision-1',governance_approved=True,human_approved=True,
            expiration='2026-10-20',strike=5800,ask=4,bid=3.8,quantity=2)

def test_build_exact_contract_and_risk():
    p=tp.make_signal(BASE,CLOCK)
    assert p['optionType']=='call' and p['strikePrice']==5800 and p['action']=='buy'
    with pytest.raises(ValueError):tp.make_signal({**BASE,'ask':11},CLOCK)
    with pytest.raises(ValueError):tp.make_signal({**BASE,'human_approved':False},CLOCK)
    with pytest.raises(ValueError):tp.make_signal({**BASE,'ticker':'SPY'},CLOCK)
    with pytest.raises(ValueError):tp.make_signal({**BASE,'quantity':True},CLOCK)
    with pytest.raises(ValueError):tp.make_signal(BASE,datetime(2026,10,24,14,tzinfo=timezone.utc))

def test_fail_closed(monkeypatch,tmp_path):
    monkeypatch.delenv('APEX_TRADERSPOST_MODE',raising=False)
    with pytest.raises(ValueError):tp.dispatch(BASE,db_path=tmp_path/'paper.db',clock=CLOCK)

def test_legacy_dispatch_blocked_but_independent_quote_grader_retained(monkeypatch,tmp_path):
    monkeypatch.setenv('APEX_TRADERSPOST_MODE','paper')
    monkeypatch.setenv('APEX_TRADERSPOST_PAPER_CONFIRMED','true')
    monkeypatch.setenv('APEX_TRADERSPOST_SEND_ENABLED','true')
    monkeypatch.setenv('APEX_TRADERSPOST_WEBHOOK_URL','https://webhooks.traderspost.io/trading/webhook/uuid/password')
    db=tmp_path/'paper.db'
    with pytest.raises(ValueError,match='AUTHORITY_NOT_VERIFIED'):
        tp.dispatch(BASE,db_path=db,sender=lambda r: (_ for _ in ()).throw(AssertionError('sent')),clock=CLOCK)
    # A legacy observational signal can still receive quote-only model grading.
    with tp.connect(db) as connection:
        connection.execute('INSERT INTO paper_signals(signal_id,created_at,status,payload_json,decision_id) VALUES(?,?,?,?,?)',
             (BASE['signal_id'],CLOCK.isoformat(),'OBSERVATION_ONLY','{}',BASE['decision_id']))
    tp.record_quote(BASE['signal_id'],'entry',observed_at='2026-10-20T14:00:00Z',bid=3.8,ask=4,quantity=2,source='polygon',db_path=db)
    tp.record_quote(BASE['signal_id'],'exit',observed_at='2026-10-20T14:03:00Z',bid=5,ask=5.2,quantity=2,source='polygon',db_path=db)
    outcome=tp.grade(BASE['signal_id'],db_path=db,fee_per_contract=Decimal('0.65'))
    assert outcome['estimated_net_pnl']==197.4 and outcome['actual_fill_verified'] is False

def test_live_conflict_rejected(monkeypatch,tmp_path):
    monkeypatch.setenv('APEX_LIVE_ORDER_ROUTING_ENABLED','true')
    with pytest.raises(ValueError,match='forbids live'):
        tp.dispatch(BASE,db_path=tmp_path/'a.db',clock=CLOCK)


def test_legacy_dispatch_refuses_all_unverified_entries(monkeypatch,tmp_path):
    monkeypatch.delenv('APEX_LIVE_ORDER_ROUTING_ENABLED',raising=False)
    monkeypatch.setenv('APEX_TRADERSPOST_MODE','paper')
    monkeypatch.setenv('APEX_TRADERSPOST_PAPER_CONFIRMED','true')
    monkeypatch.setenv('APEX_TRADERSPOST_SEND_ENABLED','true')
    monkeypatch.setenv('APEX_TRADERSPOST_WEBHOOK_URL','https://webhooks.traderspost.io/trading/webhook/uuid/password')
    for i in range(4):
        with pytest.raises(ValueError,match='AUTHORITY_NOT_VERIFIED'):
            tp.dispatch({**BASE,'signal_id':f'sample-order-{i:04}'},db_path=tmp_path/'a.db',sender=lambda r: (_ for _ in ()).throw(AssertionError('sent')),clock=CLOCK)
