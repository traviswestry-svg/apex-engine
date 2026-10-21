import os
from datetime import datetime, timezone, timedelta
import pytest
from engine.execution import paper_execution_foundation as f
from engine.execution import traderspost_paper as tp

NOW = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

def test_absent_ledger_is_blocked(tmp_path):
    state = f.snapshot(db_path=tmp_path/'missing.sqlite3')
    assert not state['ready_for_unattended_orders']
    assert not state['realized_loss_enforced']

def test_observation_is_not_approval(tmp_path):
    path = tmp_path/'ledger.sqlite3'
    result = f.observe_decision('obs1','decision1',{'ticker':'SPX','strike':7000}, origin='canonical_scanner',observed_at=NOW,db_path=path)
    assert result['dispatch_authorized'] is False
    assert f.snapshot(db_path=path)['unresolved'] == 1
    with pytest.raises(ValueError,match='duplicate'):
        f.observe_decision('obs1','decision1',{'ticker':'SPX'},origin='canonical_scanner',observed_at=NOW,db_path=path)

def test_forbids_unverified_fill_promotion(tmp_path):
    path=tmp_path/'ledger.sqlite3'
    f.observe_decision('obs2','decision2',{'ticker':'SPX'},origin='canonical_scanner',observed_at=NOW,db_path=path)
    with pytest.raises(ValueError,match='trusted'):
        f.note_evidence('obs2','FILL_VERIFIED',origin='operator',observed_at=NOW,evidence={'price':10},db_path=path)
    with pytest.raises(ValueError,match='authenticated'):
        f.note_evidence('obs2','BROKER_ACKNOWLEDGED',origin='webhook',observed_at=NOW,evidence={'status':'ok'},db_path=path)
    assert f.snapshot(db_path=path)['verified_closed'] == 0

def test_unknown_delivery_preserved(tmp_path):
    path=tmp_path/'ledger.sqlite3'
    f.observe_decision('obs3','decision3',{'ticker':'SPX'},origin='canonical_scanner',observed_at=NOW,db_path=path)
    f.note_evidence('obs3','DELIVERY_UNKNOWN',origin='transport',observed_at=NOW,evidence={'timeout':True},db_path=path)
    state=f.snapshot(db_path=path)
    assert state['unresolved']==1 and not state['realized_loss_enforced']

def test_dispatch_fail_closed_even_with_caller_approval(monkeypatch):
    monkeypatch.setenv('APEX_TRADERSPOST_MODE','paper')
    monkeypatch.setenv('APEX_TRADERSPOST_PAPER_CONFIRMED','true')
    monkeypatch.setenv('APEX_TRADERSPOST_SEND_ENABLED','true')
    monkeypatch.setenv('APEX_TRADERSPOST_WEBHOOK_URL','https://webhooks.traderspost.io/trading/webhook/fake/secret')
    monkeypatch.setenv('APEX_LIVE_ORDER_ROUTING_ENABLED','false')
    with pytest.raises(ValueError,match='AUTHORITY_NOT_VERIFIED'):
        tp.dispatch({'governance_approved': True,'human_approved':True}, sender=lambda req: (_ for _ in ()).throw(AssertionError('sent')))
