import json
import tempfile
from pathlib import Path

from engine import feature_store_db as D
from engine import flow_pl_store as S
from engine import feature_store_writer as W
from engine.flow_pl_pipeline import capture_persisted_feature_excursions

SESSION = "2026-08-26"
FRAMES = [{"session_date": SESSION, "frame_time": "10:31:00", "ticker": "SPX",
           "snapshot_json": '{"gamma_regime":"POSITIVE","ici":72,"stock_price":6500.0}'}]


def _init(monkeypatch):
    tmp=tempfile.NamedTemporaryFile(suffix='.db', delete=False); tmp.close()
    monkeypatch.setattr(D, '_DB_PATH', tmp.name); monkeypatch.setattr(S, '_DB_PATH', tmp.name)
    D._DB_READY=False; S._DB_READY=False
    assert D.init_db(); assert S.init_db()


def _cluster(pl=125.0):
    key='SPX|CALL|2026-08-26|BULLISH'
    return {"ticker":"SPX","option_type":"CALL","expiration":"2026-08-26",
            "directional_interpretation":"BULLISH",
            "cluster_key":{"ticker":"SPX","option_type":"CALL","expiration":"2026-08-26","directional_interpretation":"BULLISH"},
            "cluster_key_string":key,"start_time":"10:31:02","end_time":"10:31:11",
            "duration_seconds":9,"number_of_prints":4,"total_premium":1000000,
            "total_contracts":100,"weighted_average_execution_price":5.0,
            "aggression_score":90.0,"repeat_intensity_score":75.0,"distinct_contracts":2,
            "premium_concentration":0.5,"confidence":0.7,"strike_range":[6500.0,6510.0],
            "intent_uncertainty":{"score":0.2},
            "_excursion_observation":{"pl_dollars":pl,"cost_basis":1000.0,"ticker":"SPX","legacy_cluster_key":key}}


def test_release_truth_6943():
    d=json.loads(Path('config/apex_release_manifest.json').read_text())
    assert tuple(map(int,d['apex_version'].split('.'))) >= (69,4,3)
    g=d['guardrails']
    assert g['scanner_flow_excursion_capture_post_feature_persistence'] is True
    assert g['scanner_flow_excursion_capture_uses_canonical_sample_id_only'] is True
    assert g['scanner_flow_learning_store_initialization_explicit'] is True
    assert g['flow_excursion_backfill_fabrication_allowed'] is False
    assert g['flow_settlement_requirements_relaxed'] is False


def test_scanner_deferred_capture_happens_after_feature_persistence(monkeypatch):
    _init(monkeypatch)
    rep=W.write_samples(priced_clusters=[_cluster()], replay_rows=FRAMES,
                        session_date=SESSION, now_et_seconds=10*3600+35*60,
                        defer_excursion_capture=True)
    assert rep['written']==1
    assert rep['excursions_inserted']==0
    assert len(rep['capture_targets'])==1
    sid=rep['capture_targets'][0]['sample_id']
    assert D.get_features(sid) is not None
    assert S.get_sample_excursions([sid]) == {}
    cap=capture_persisted_feature_excursions(rep['capture_targets'])
    assert cap['attempted']==1 and cap['inserted']==1 and cap['errors']==0
    assert S.get_sample_excursions([sid])[sid]['samples']==1


def test_subsequent_real_mark_widens_same_canonical_sample(monkeypatch):
    _init(monkeypatch)
    first=W.write_samples(priced_clusters=[_cluster(100.0)], replay_rows=FRAMES,
                          session_date=SESSION, now_et_seconds=10*3600+35*60,
                          defer_excursion_capture=True)
    capture_persisted_feature_excursions(first['capture_targets'])
    second=W.write_samples(priced_clusters=[_cluster(900.0)], replay_rows=FRAMES,
                           session_date=SESSION, now_et_seconds=10*3600+36*60,
                           defer_excursion_capture=True)
    assert second['already_present']==1
    out=capture_persisted_feature_excursions(second['capture_targets'])
    sid=second['capture_targets'][0]['sample_id']
    row=S.get_sample_excursions([sid])[sid]
    assert out['updated']==1
    assert row['samples']==2 and row['mfe_dollars']==900.0 and row['mae_dollars']==100.0


def test_missing_real_pl_is_counted_not_fabricated(monkeypatch):
    _init(monkeypatch)
    rep=W.write_samples(priced_clusters=[_cluster(None)], replay_rows=FRAMES,
                        session_date=SESSION, now_et_seconds=10*3600+35*60,
                        defer_excursion_capture=True)
    out=capture_persisted_feature_excursions(rep['capture_targets'])
    assert out['attempted']==1 and out['missing_pl']==1 and out['inserted']==0
    h=S.sample_excursion_health()
    assert h['sample_excursions']==0 and h['capture']['missing_pl']==1


def test_production_scanner_explicitly_initializes_and_invokes_capture():
    src=Path('scanner_worker.py').read_text()
    assert '_ensure_flow_learning_stores()' in src
    assert 'flow_excursion_capture' in src
    app=Path('app.py').read_text()
    assert 'defer_excursion_capture=True' in app
    assert '_flow_pl_capture_persisted' in app
