import json
from pathlib import Path


def test_release_metadata_ratchet():
    root=Path(__file__).resolve().parents[1]
    m=json.loads((root/'config/apex_release_manifest.json').read_text())
    assert m['apex_version']==m['semantic_version']==m['application_version']=='69.10.18'
    assert m['database_schema_version']=='6'
    assert m['guardrails']['durable_settlement_reconciliation'] is True
    assert m['guardrails']['gamma_linkage_historical_reconstruction'] is False
    assert m['guardrails']['gamma_linkage_latest_snapshot_substitution'] is False


def test_durable_settlement_round_trip(monkeypatch,tmp_path):
    monkeypatch.setenv('APEX_PERSISTENT_DISK_PATH',str(tmp_path))
    monkeypatch.delenv('APEX_FLOW_SETTLEMENT_RECONCILIATION_PATH',raising=False)
    from engine.operational_runtime import write_settlement_reconciliation,read_settlement_reconciliation
    write_settlement_reconciliation({'state':'COMPLETED','last_result':{'canonical_excursion_rows_found':7,'labelled':5}})
    out=read_settlement_reconciliation()
    assert out['available'] is True
    assert out['version']=='69.10.18'
    assert out['last_result']['canonical_excursion_rows_found']==7
    assert out['last_result']['labelled']==5
    assert out['execution_authority'] is False


def test_scheduler_persists_completed_settlement(monkeypatch,tmp_path):
    monkeypatch.setenv('APEX_PERSISTENT_DISK_PATH',str(tmp_path))
    monkeypatch.delenv('APEX_FLOW_SETTLEMENT_RECONCILIATION_PATH',raising=False)
    from engine import flow_settlement_scheduler as mod
    monkeypatch.setattr(mod.feature_store_writer,'settle_pending_labels',lambda **kw:{'state':'COMPLETED','canonical_excursion_rows_found':4,'labelled':3})
    sched=mod.FlowSettlementScheduler(enabled=True,interval_seconds=60)
    out=sched.run_if_due(force=True)
    from engine.operational_runtime import read_settlement_reconciliation
    durable=read_settlement_reconciliation()
    assert out['state']=='COMPLETED'
    assert durable['last_result']['labelled']==3


def test_release_scoped_gamma_linkage_does_not_reconstruct(tmp_path):
    from engine import evidence_pipeline as ep
    db=tmp_path/'evidence.db'
    with ep._connect(db) as c:
        c.execute("INSERT INTO decisions(decision_id,observed_at,ticker,learning_eligible,snapshot_json,canonical_gamma_snapshot_id) VALUES(?,?,?,?,?,?)",('legacy','2026-09-17T13:30:00Z','SPX',1,json.dumps({'apex_release_version':'69.10.14'}),None))
        c.execute("INSERT INTO decisions(decision_id,observed_at,ticker,learning_eligible,snapshot_json,canonical_gamma_snapshot_id) VALUES(?,?,?,?,?,?)",('new-linked','2026-09-21T13:30:00Z','SPX',1,json.dumps({'apex_release_version':'69.10.18'}),'g1'))
        c.execute("INSERT INTO decisions(decision_id,observed_at,ticker,learning_eligible,snapshot_json,canonical_gamma_snapshot_id) VALUES(?,?,?,?,?,?)",('new-missing','2026-09-21T13:31:00Z','SPX',1,json.dumps({'apex_release_version':'69.10.18'}),None))
    r=ep.readiness(db)['gamma_release_linkage']['current_release']
    assert r['decisions']==2 and r['gamma_linked']==1 and r['gamma_missing']==1
    assert r['legacy_rows_reconstructed']==0
    assert r['latest_gamma_substitution_allowed'] is False
