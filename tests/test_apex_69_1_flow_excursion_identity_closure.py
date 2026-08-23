import tempfile
from pathlib import Path

from engine import feature_store_db as D
from engine import flow_pl_store as S
from engine import feature_store_writer as W
from engine.feature_store import Feature, build_pre_decision_vector
from engine.historical_evidence_lifecycle import VERSION, SCHEMA_VERSION


def _init(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp.close()
    monkeypatch.setattr(D, '_DB_PATH', tmp.name)
    monkeypatch.setattr(S, '_DB_PATH', tmp.name)
    D._DB_READY = False
    S._DB_READY = False
    assert D.init_db()
    assert S.init_db()
    return Path(tmp.name)


def _vector(sample_id, decision='2026-08-24T10:00:00-04:00'):
    feats = [
        Feature('cluster_option_type', 'CALL', decision, 'flow_cluster'),
        Feature('cluster_expiration', '2026-08-24', decision, 'flow_cluster'),
        Feature('cluster_directional_interpretation', 'BULLISH', decision, 'flow_cluster'),
    ]
    return build_pre_decision_vector(sample_id=sample_id, decision_time=decision,
                                     ticker='SPX', features=feats,
                                     session_date='2026-08-24')


def test_release_identity_69_1():
    assert VERSION == '69.1.0'
    assert SCHEMA_VERSION == 'apex.historical_evidence_lifecycle.v1.3'
    registry = Path('config/apex_capability_registry.yaml').read_text()
    import re
    m = re.search(r'^apex_version:\s*([0-9]+\.[0-9]+\.[0-9]+)', registry, re.M)
    assert m and tuple(map(int, m.group(1).split('.'))) >= (69, 1, 0)


def test_canonical_sample_excursion_settles_exact_sample(monkeypatch):
    _init(monkeypatch)
    assert D.write_features(_vector('sample-A'))
    assert D.write_features(_vector('sample-B', '2026-08-24T10:01:00-04:00'))
    # Same legacy cluster key, two different immutable samples. Only sample-A has evidence.
    assert S.record_sample_excursion(sample_id='sample-A', session_date='2026-08-24',
                                     ticker='SPX', pl_dollars=100.0, cost_basis=1000.0,
                                     decision_time='2026-08-24T10:00:00-04:00',
                                     legacy_cluster_key='SPX|CALL|2026-08-24|BULLISH')
    assert S.record_sample_excursion(sample_id='sample-A', session_date='2026-08-24',
                                     ticker='SPX', pl_dollars=1500.0, cost_basis=1000.0,
                                     decision_time='2026-08-24T10:00:00-04:00',
                                     legacy_cluster_key='SPX|CALL|2026-08-24|BULLISH')
    out = W.settle_labels(session_date='2026-08-24')
    assert out['canonical_excursion_rows_found'] == 1
    assert out['labelled'] == 1
    assert out['ambiguous_legacy_vectors'] == 2
    assert out['missing_excursion_row'] == 1
    assert D.get_label('sample-A') is not None
    assert D.get_label('sample-B') is None


def test_legacy_coarse_key_never_labels_ambiguous_vectors(monkeypatch):
    _init(monkeypatch)
    assert D.write_features(_vector('sample-A'))
    assert D.write_features(_vector('sample-B', '2026-08-24T10:01:00-04:00'))
    S.record_cluster_observation(cluster_key='SPX|CALL|2026-08-24|BULLISH',
                                 session_date='2026-08-24', ticker='SPX',
                                 pl_dollars=500.0, cost_basis=1000.0)
    out = W.settle_labels(session_date='2026-08-24')
    assert out['legacy_singleton_candidates'] == 0
    assert out['legacy_singleton_recoveries'] == 0 if 'legacy_singleton_recoveries' in out else True
    assert out['labelled'] == 0
    assert out['missing_excursion_row'] == 2
