from datetime import datetime, timezone, timedelta
import sqlite3
import pytest
from engine.execution import paper_execution_foundation as f

WHEN = (datetime.now(timezone.utc)-timedelta(seconds=30)).isoformat()
CONTRACT = {"ticker":"SPX", "strike":7000,"side":"CALL","expiry":"2026-10-21"}

def row(decision_id):
    return {"decision_id":decision_id,"record_id":"persisted-123", "origin":"canonical_decision_store", "contract":CONTRACT, "persisted":True}

def test_initialize_durable_idempotent(tmp_path):
    db=tmp_path/'paper.sqlite3'
    assert f.snapshot(db_path=db)['ledger_state']=='NOT_INITIALIZED'
    for _ in range(2):
        assert f.initialize_ledger(db_path=db)['ledger_state']=='AVAILABLE'
    assert f.snapshot(db_path=db)['ledger_state']=='AVAILABLE'
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='paper_decision_bindings'").fetchone()

def test_initialize_missing_parent_fails_closed(tmp_path):
    with pytest.raises(RuntimeError,match='PARENT_MISSING'):
        f.initialize_ledger(db_path=tmp_path/'absent'/'db.sqlite3')

def test_exact_canonical_identity_binding_is_observation_only(tmp_path):
    db=tmp_path/'paper.sqlite3'
    result=f.bind_canonical_observation('lifecycle-1','d-1',CONTRACT,trusted_reader=row,observed_at=WHEN,db_path=db)
    assert result['canonical_bound'] and not result['dispatch_authorized']
    assert f.snapshot(db_path=db)['unresolved']==1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT canonical_decision_id FROM paper_decision_bindings").fetchone()[0]=='d-1'
    with pytest.raises(ValueError,match='duplicate'):
        f.bind_canonical_observation('lifecycle-1','d-1',CONTRACT,trusted_reader=row,observed_at=WHEN,db_path=db)

def test_untrusted_or_unpersisted_records_rejected(tmp_path):
    db=tmp_path/'paper.sqlite3'
    bad=[None,{}, {**row('d-1'),'origin':'operator_assertion'}, {**row('d-1'),'persisted':False}, {**row('d-1'),'contract':{'ticker':'SPX'}}, {**row('d-1'),'decision_id':'other'}]
    for value in bad:
        with pytest.raises(ValueError):
            f.bind_canonical_observation('lifecycle-1','d-1',CONTRACT,trusted_reader=lambda _:value,observed_at=WHEN,db_path=db)
    assert f.snapshot(db_path=db)['ledger_state']=='NOT_INITIALIZED'

def test_no_untrusted_promotion(tmp_path):
    db=tmp_path/'paper.sqlite3'
    f.bind_canonical_observation('lifecycle-2','d-2',CONTRACT,trusted_reader=row,observed_at=WHEN,db_path=db)
    with pytest.raises(ValueError):
        f.note_evidence('lifecycle-2','FILL_VERIFIED',origin='webhook',observed_at=WHEN,evidence={'price':1},db_path=db)
    assert not f.snapshot(db_path=db)['realized_loss_enforced']
