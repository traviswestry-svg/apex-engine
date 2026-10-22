from datetime import datetime, timezone
from engine.execution.paper_order_preflight import inspect

CLOCK = datetime(2026, 10, 22, 14, 0, tzinfo=timezone.utc)
CONTRACT = {'ticker': 'SPX', 'side': 'CALL', 'strike': 7000, 'expiry': '2026-10-22'}
CANDIDATE = {'ticker': 'SPX', 'contract': CONTRACT, 'decision_id':'abc', 'quantity': 1, 'ask':'2.5','bid':'2.4'}


def reader(key):
    return {'persisted': True, 'decision_id':key, 'contract':CONTRACT}


def test_valid_candidate_still_cannot_send(monkeypatch):
    monkeypatch.setenv('APEX_TRADERSPOST_MODE', 'paper')
    monkeypatch.setenv('APEX_TRADERSPOST_PAPER_CONFIRMED','true')
    result=inspect(CANDIDATE,clock=CLOCK,decision_reader=reader)
    assert result['candidate_checked']
    assert not result['may_send_order'] and not result['ready_for_unattended_orders']
    assert 'BROKER_RECONCILIATION_OPERATIONAL' in result['blockers']
    assert 'PERSISTED_CANONICAL_DECISION_NOT_FOUND' not in result['blockers']


def test_no_test_true_promotion():
    r=inspect(dict(CANDIDATE,test=False,governance_approved=True,human_approved=True),clock=CLOCK,decision_reader=reader)
    assert not r['may_send_order']


def test_missing_record_and_mismatch():
    assert 'PERSISTED_CANONICAL_DECISION_NOT_FOUND' in inspect(CANDIDATE,clock=CLOCK,decision_reader=lambda _:None)['blockers']
    assert 'CANONICAL_CONTRACT_MISMATCH' in inspect(CANDIDATE,clock=CLOCK,decision_reader=lambda k:{'persisted':True,'decision_id':k,'contract':{'ticker':'SPX'}})['blockers']


def test_reject_missing_contract_risky_debit():
    invalid=dict(CANDIDATE,contract={'ticker':'SPY'},quantity=3,ask='10',bid='9')
    blockers=inspect(invalid,clock=CLOCK,decision_reader=reader)['blockers']
    assert 'EXACT_SPX_OPTION_CONTRACT_REQUIRED' in blockers
    assert 'ENTRY_DEBIT_EXCEEDS_2000' in blockers


def test_outside_window():
    result=inspect(CANDIDATE,clock=datetime(2026,10,22,20,0,tzinfo=timezone.utc),decision_reader=reader)
    assert 'WITHIN_ENTRY_WINDOW' in result['blockers']
