import json
from pathlib import Path

from engine import feature_store_db, flow_pl_store, feature_store_writer


def _init(monkeypatch, tmp_path):
    db=str(tmp_path/'tracking.db')
    monkeypatch.setenv('DB_PATH', db)
    feature_store_db._DB_PATH=None; flow_pl_store._DB_PATH=None
    feature_store_db._DB_READY=False; flow_pl_store._DB_READY=False
    assert feature_store_db.init_db(); assert flow_pl_store.init_db()
    return db


def test_release_truth_and_guardrails():
    d=json.loads(Path('config/apex_release_manifest.json').read_text())
    assert d['apex_version']=='69.10.19'
    assert d['build_name']=='Canonical Feature Sample P/L Excursion Linkage Closure'
    assert d['guardrails']['canonical_identity_join_reconstructs_identity'] is False
    assert d['guardrails']['canonical_identity_join_writes_evidence'] is False


def test_identity_join_audit_distinguishes_registered_without_excursion(monkeypatch,tmp_path):
    _init(monkeypatch,tmp_path)
    sid='s_exact'
    assert flow_pl_store.register_sample_identity(sample_id=sid,session_date='2026-09-22',legacy_cluster_key='k',decision_time='2026-09-22T10:00:00')
    out=flow_pl_store.audit_sample_identity_join([sid],session_date='2026-09-22')
    assert out['identity_map_matches']==1
    assert out['excursion_matches']==0
    assert out['registered_without_excursion']==1
    assert out['feature_only_ids']==0
    assert out['writes_evidence'] is False
    assert out['reconstructs_identity'] is False


def test_identity_join_audit_exact_three_table_match(monkeypatch,tmp_path):
    _init(monkeypatch,tmp_path)
    sid='s_exact'
    assert flow_pl_store.register_sample_identity(sample_id=sid,session_date='2026-09-22',legacy_cluster_key='k',decision_time='2026-09-22T10:00:00')
    assert flow_pl_store.record_sample_excursion(sample_id=sid,session_date='2026-09-22',ticker='SPX',pl_dollars=25.0,cost_basis=100.0,decision_time='2026-09-22T10:00:00',legacy_cluster_key='k')
    out=flow_pl_store.audit_sample_identity_join([sid],session_date='2026-09-22')
    assert out['exact_three_table_matches']==1
    assert out['identity_tuple_mismatches']==0
    assert out['registered_without_excursion']==0


def test_settlement_exposes_join_audit_without_relaxing_exact_lookup(monkeypatch,tmp_path):
    _init(monkeypatch,tmp_path)
    # Direct feature row with a registered identity but deliberately no excursion.
    v={'sample_id':'s_pending','session_date':'2026-09-22','ticker':'SPX','decision_time':'2026-09-22T10:00:00','features':{},'feature_availability':{},'max_feature_lag_seconds':0,'feature_count':0,'schema_version':'x'}
    assert feature_store_db.write_features(v)
    assert flow_pl_store.register_sample_identity(sample_id='s_pending',session_date='2026-09-22',legacy_cluster_key='k',decision_time='2026-09-22T10:00:00')
    out=feature_store_writer.settle_labels(session_date='2026-09-22')
    a=out['canonical_identity_join_audit']
    assert a['identity_map_matches']==1
    assert a['registered_without_excursion']==1
    assert out['canonical_excursion_rows_found']==0
    assert out['labelled']==0
    assert out['missing_excursion_row']==1
