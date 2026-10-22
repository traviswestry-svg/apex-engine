import json
import sqlite3
from datetime import datetime, timezone
from engine.execution.paper_execution_foundation import (
    initialize_ledger, snapshot, canonical_binding_health,
    bind_persisted_canonical_observation, persisted_canonical_reader)


def test_restart_persistence_and_no_order_authority(tmp_path):
    path = tmp_path / 'ledger.db'
    assert initialize_ledger(db_path=path)['ledger_state'] == 'AVAILABLE'
    assert initialize_ledger(db_path=path)['ledger_state'] == 'AVAILABLE'
    state = snapshot(db_path=path)
    assert state['ledger_state'] == 'AVAILABLE'
    assert state['ready_for_unattended_orders'] is False


def test_canonical_reader_exact_identity_and_contract(tmp_path):
    store = tmp_path / 'evidence.db'; ledger = tmp_path / 'paper.db'
    contract = {'ticker':'SPX','expiration':'2026-10-22','right':'C','strike':5800}
    with sqlite3.connect(store) as c:
        c.execute('CREATE TABLE decisions (decision_id TEXT, observed_at TEXT, ticker TEXT, snapshot_json TEXT)')
        c.execute('INSERT INTO decisions VALUES (?,?,?,?)', ('d42','2026-10-22T13:00:00+00:00','SPX',json.dumps({'institutional_decision_object':{'authoritative_contract': contract}})))
    assert canonical_binding_health(evidence_db=store)['operational']
    assert persisted_canonical_reader('d42', evidence_db=store)['contract'] == contract
    at = datetime.now(timezone.utc).isoformat()
    result = bind_persisted_canonical_observation('l42','d42',contract,observed_at=at, db_path=ledger, evidence_db=store)
    assert result['canonical_bound'] and result['dispatch_authorized'] is False
    assert snapshot(db_path=ledger)['records'] == 1
    import pytest
    with pytest.raises(ValueError, match='duplicate'):
        bind_persisted_canonical_observation('l42','d42',contract,observed_at=at,db_path=ledger,evidence_db=store)
    with pytest.raises(ValueError, match='MISMATCH'):
        bind_persisted_canonical_observation('l43','d42',{'ticker':'SPX'},observed_at=at,db_path=ledger,evidence_db=store)
