import json
from pathlib import Path

from engine import feature_store_db, flow_pl_store
from engine.feature_store import Feature, build_pre_decision_vector
from engine.feature_store_writer import _capture_exact_persisted_sample


def _use_db(monkeypatch, tmp_path):
    db = tmp_path / "tracking.db"
    monkeypatch.setattr(feature_store_db, "_DB_PATH", str(db))
    monkeypatch.setattr(flow_pl_store, "_DB_PATH", str(db))
    feature_store_db.init_db(); flow_pl_store.init_db()
    return db


def test_release_truth_and_guardrails():
    d=json.loads(Path('config/apex_release_manifest.json').read_text())
    assert d['apex_version']=='69.10.19'
    assert d['build_name']=='Canonical Feature Sample P/L Excursion Linkage Closure'
    assert d['guardrails']['sample_pl_reconstruction_allowed'] is False
    assert d['guardrails']['synthetic_excursion_allowed'] is False
    assert d['guardrails']['fuzzy_sample_recovery_allowed'] is False


def test_registered_sample_without_pl_is_durable_awaiting_state(monkeypatch, tmp_path):
    _use_db(monkeypatch,tmp_path)
    sid='s_exact_awaiting'; dt='2026-09-23T10:00:00'; key='SPX|CALL|2026-09-23|BULLISH'
    vec=build_pre_decision_vector(sample_id=sid, decision_time=dt, ticker='SPX', session_date='2026-09-23', features=[Feature(name='x',value=1,available_at=dt,source='t')])
    assert feature_store_db.write_features(vec)
    rep={'canonical_lookup_missing':0,'excursion_capture_attempts':0,'excursion_capture_errors':0,'reasons':[], 'identity_registration_failures':0,'capture_targets':[], 'excursion_missing_pl':0,'excursions_inserted':0,'excursions_updated':0}
    _capture_exact_persisted_sample(report=rep,sid=sid,session_date='2026-09-23',ticker='SPX',decision_time=dt,legacy_cluster_key=key,excursion={'pl_dollars':None,'cost_basis':100},defer_excursion_capture=False)
    h=flow_pl_store.sample_pl_lifecycle_health()
    assert h['states']['AWAITING_REAL_PL']==1
    assert flow_pl_store.get_sample_excursions([sid]) == {}


def test_exact_later_real_pl_closes_lifecycle_without_reconstruction(monkeypatch, tmp_path):
    _use_db(monkeypatch,tmp_path)
    sid='s_exact_later'; dt='2026-09-23T10:01:00'; key='SPX|PUT|2026-09-23|BEARISH'
    assert flow_pl_store.register_sample_identity(sample_id=sid,session_date='2026-09-23',legacy_cluster_key=key,decision_time=dt)
    flow_pl_store.record_sample_pl_lifecycle(sample_id=sid,session_date='2026-09-23',legacy_cluster_key=key,decision_time=dt,state='AWAITING_REAL_PL',reason='test')
    identity=flow_pl_store.resolve_exact_sample_identity(session_date='2026-09-23',legacy_cluster_key=key,decision_time=dt)
    assert identity['sample_id']==sid
    cap=flow_pl_store.record_sample_excursion(sample_id=sid,session_date='2026-09-23',ticker='SPX',pl_dollars=25.0,cost_basis=100.0,decision_time=dt,legacy_cluster_key=key)
    assert cap and cap['first_sample']
    assert flow_pl_store.record_sample_pl_lifecycle(sample_id=sid,session_date='2026-09-23',legacy_cluster_key=key,decision_time=dt,state='PL_OBSERVED_EXCURSION_WRITTEN',reason='LATER_EXACT_TUPLE_REAL_PL',pl_observed=True,excursion_written=True)
    h=flow_pl_store.sample_pl_lifecycle_health()
    assert h['states']['PL_OBSERVED_EXCURSION_WRITTEN']==1
    assert h['pl_observations']==1 and h['excursion_writes']==1
    assert sid in flow_pl_store.get_sample_excursions([sid])


def test_nonexact_tuple_never_resolves(monkeypatch,tmp_path):
    _use_db(monkeypatch,tmp_path)
    assert flow_pl_store.register_sample_identity(sample_id='s_one',session_date='2026-09-23',legacy_cluster_key='K',decision_time='2026-09-23T10:00:00')
    assert flow_pl_store.resolve_exact_sample_identity(session_date='2026-09-23',legacy_cluster_key='K',decision_time='2026-09-23T10:00:01') is None
