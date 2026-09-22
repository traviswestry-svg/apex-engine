import json
import os
import sqlite3

from engine import feature_store_db as features
from engine import flow_pl_store as excursions
from engine import feature_store_writer as writer


def test_release_truth_69_10_17():
    m=json.load(open('config/apex_release_manifest.json'))
    assert m['apex_version']==m['semantic_version']==m['application_version']=='69.10.19'
    assert m['build_name']=='Canonical Feature Sample P/L Excursion Linkage Closure'


def test_flow_store_db_path_is_dynamic_after_import(monkeypatch, tmp_path):
    # Production can inject DB_PATH after modules are imported.  69.10.17 must
    # follow the active canonical authority instead of retaining import-time cwd.
    excursions._DB_PATH=None
    a=str(tmp_path/'a.db'); b=str(tmp_path/'b.db')
    monkeypatch.setenv('DB_PATH', a)
    assert excursions.active_db_path()==a
    monkeypatch.setenv('DB_PATH', b)
    assert excursions.active_db_path()==b


def _init_same_db(monkeypatch, db):
    monkeypatch.setenv('DB_PATH', str(db))
    monkeypatch.setattr(features, '_DB_PATH', None)
    monkeypatch.setattr(excursions, '_DB_PATH', None)
    assert features.init_db()
    assert excursions.init_db()


def test_exact_feature_sample_joins_exact_excursion_and_labels(monkeypatch, tmp_path):
    db=tmp_path/'canonical.db'; _init_same_db(monkeypatch, db)
    sid='s_691017_exact'
    vector={
      'sample_id':sid,'session_date':'2026-09-22','ticker':'SPX',
      'decision_time':'2026-09-22T10:00:00','features':{
        'cluster_option_type':'CALL','cluster_expiration':'2026-09-22',
        'cluster_directional_interpretation':'BULLISH'},
      'feature_availability':{},'max_feature_lag_seconds':0,'feature_count':3,
      'schema_version':'test'}
    assert features.write_features(vector)
    assert excursions.register_sample_identity(sample_id=sid,session_date='2026-09-22',
      legacy_cluster_key='SPX|CALL|2026-09-22|BULLISH',decision_time=vector['decision_time'])
    assert excursions.record_sample_excursion(sample_id=sid,session_date='2026-09-22',ticker='SPX',
      pl_dollars=50.0,cost_basis=100.0,decision_time=vector['decision_time'],
      legacy_cluster_key='SPX|CALL|2026-09-22|BULLISH')
    out=writer.settle_labels(session_date='2026-09-22')
    assert out['persistence_authority']['match'] is True
    assert out['canonical_excursion_rows_found']==1
    assert out['labelled']==1
    assert out['missing_excursion_row']==0


def test_settlement_fails_closed_on_persistence_authority_mismatch(monkeypatch, tmp_path):
    fdb=tmp_path/'features.db'; edb=tmp_path/'excursions.db'
    monkeypatch.setattr(features, '_DB_PATH', str(fdb)); assert features.init_db()
    monkeypatch.setattr(excursions, '_DB_PATH', str(edb)); assert excursions.init_db()
    out=writer.settle_labels(session_date='2026-09-22')
    assert out['state']=='PERSISTENCE_AUTHORITY_MISMATCH'
    assert out['persistence_authority']['match'] is False
    assert out['labelled']==0


def test_no_fuzzy_or_latest_identity_fallback_added():
    src=open('engine/feature_store_writer.py').read()
    # Settlement must continue selecting canonical excursions by exact sample IDs.
    assert 'get_sample_excursions(sample_ids)' in src
    assert 'CANONICAL_FEATURE_SAMPLE_ID' in src
