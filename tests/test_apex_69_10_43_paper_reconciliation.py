import sqlite3
from datetime import datetime, timezone, timedelta
import pytest
from engine.execution import paper_execution_foundation as foundation
from engine.execution import paper_reconciliation as recon

WHEN=(datetime.now(timezone.utc)-timedelta(seconds=45)).isoformat()
CONTRACT={'ticker':'SPX','strike':7000,'side':'CALL','expiry':'2026-10-22'}

def _canonical(did):
    return {'decision_id':did,'record_id':did,'origin':'canonical_decision_store',
            'contract':CONTRACT,'persisted':True}

def _event(eid='evt1'):
    return {'event_id':eid,'order_id':'order1','event_type':'ENTRY_FILL','quantity':1,
            'price':'1.50','observed_at':WHEN,'decision_id':'decision1','contract':CONTRACT,
            'source':'authenticated_broker_order_feed','authenticated':True}

def _bound(tmp_path):
    path=tmp_path/'paper.db'
    foundation.bind_canonical_observation('life1','decision1',CONTRACT,
        trusted_reader=_canonical,observed_at=WHEN,db_path=path)
    return path

def test_initialize_idempotent_and_survives_restart(tmp_path):
    path=tmp_path/'paper.db'
    for _ in range(2):
        assert recon.initialize_reconciliation(db_path=path)['reconciliation_journal']=='AVAILABLE'
    assert recon.reconciliation_health(db_path=path)['journal_state']=='AVAILABLE'
    assert not recon.reconciliation_health(db_path=path)['broker_reconciliation_operational']

def test_valid_trusted_event_is_quarantined_not_fill(tmp_path):
    path=_bound(tmp_path)
    r=recon.validate_trusted_event('life1','evt1',trusted_reader=lambda _: _event(),db_path=path)
    assert r['verdict']=='QUARANTINED_UNRECONCILED' and not r['fill_verified']
    assert recon.reconciliation_health(db_path=path)['quarantined_events']==1
    assert foundation.snapshot(db_path=path)['verified_closed']==0
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT state FROM paper_lifecycle').fetchone()[0]=='DECISION_OBSERVED'
    with pytest.raises(ValueError,match='DUPLICATE'):
        recon.validate_trusted_event('life1','evt1',trusted_reader=lambda _: _event(),db_path=path)

def test_untrusted_missing_and_mismatched_events_fail_closed(tmp_path):
    path=_bound(tmp_path)
    invalid=[None,{},dict(_event(),authenticated=False),dict(_event(),decision_id='wrong'),
             dict(_event(),contract={'ticker':'SPY'}),dict(_event(),quantity=0),
             dict(_event(),price='NaN'),dict(_event(),observed_at='2099-01-01T00:00:00Z'),
             dict(_event(),source='webhook')]
    for ev in invalid:
        with pytest.raises(ValueError):
            recon.validate_trusted_event('life1','evt1',trusted_reader=lambda _, e=ev:e,db_path=path)
    assert recon.reconciliation_health(db_path=path)['quarantined_events']==0

def test_webhook_cannot_promote_verified_fill(tmp_path):
    path=_bound(tmp_path)
    with pytest.raises(ValueError):
        foundation.note_evidence('life1','FILL_VERIFIED',origin='webhook',observed_at=WHEN,evidence={},db_path=path)
