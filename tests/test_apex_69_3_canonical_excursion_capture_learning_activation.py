import json
import tempfile
from pathlib import Path

from engine import feature_store_db as D
from engine import flow_pl_store as S
from engine import feature_store_writer as W
from engine.historical_evidence_lifecycle import VERSION, SCHEMA_VERSION

SESSION = "2026-08-24"
FRAMES = [{
    "session_date": SESSION,
    "frame_time": "10:31:00",
    "ticker": "SPX",
    "snapshot_json": '{"gamma_regime":"POSITIVE","ici":72,"stock_price":6500.0}',
}]


def _init(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr(D, "_DB_PATH", tmp.name)
    monkeypatch.setattr(S, "_DB_PATH", tmp.name)
    D._DB_READY = False
    S._DB_READY = False
    assert D.init_db()
    assert S.init_db()
    return Path(tmp.name)


def _cluster(pl=100.0, cost=1000.0):
    key = "SPX|CALL|2026-08-24|BULLISH"
    return {
        "ticker": "SPX",
        "option_type": "CALL",
        "expiration": "2026-08-24",
        "directional_interpretation": "BULLISH",
        "cluster_key": {"ticker": "SPX", "option_type": "CALL", "expiration": "2026-08-24",
                        "directional_interpretation": "BULLISH"},
        "cluster_key_string": key,
        "start_time": "10:31:02",
        "end_time": "10:31:11",
        "duration_seconds": 9,
        "number_of_prints": 4,
        "total_premium": 1000000,
        "total_contracts": 100,
        "weighted_average_execution_price": 5.0,
        "aggression_score": 90.0,
        "repeat_intensity_score": 75.0,
        "distinct_contracts": 2,
        "premium_concentration": 0.5,
        "confidence": 0.7,
        "strike_range": [6500.0, 6510.0],
        "intent_uncertainty": {"score": 0.2},
        "_excursion_observation": {
            "pl_dollars": pl,
            "cost_basis": cost,
            "ticker": "SPX",
            "legacy_cluster_key": key,
        },
    }


def _sealed_seconds():
    return 10 * 3600 + 35 * 60


def test_release_identity_69_3_and_guardrails():
    manifest = json.loads(Path("config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == "69.3.0"
    assert manifest["build_name"] == "Canonical Excursion Capture & Learning Activation Closure"
    assert VERSION == "69.3.0"
    assert SCHEMA_VERSION == "apex.historical_evidence_lifecycle.v1.4"
    g = manifest["guardrails"]
    assert g["canonical_excursion_capture_requires_feature_sample"] is True
    assert g["canonical_excursion_identity_is_feature_sample_id"] is True
    assert g["flow_excursion_capture_creates_synthetic_evidence"] is False
    assert g["flow_label_requirements_relaxed"] is False


def test_new_feature_creates_canonical_excursion_only_after_feature_persisted(monkeypatch):
    _init(monkeypatch)
    out = W.write_samples(priced_clusters=[_cluster()], replay_rows=FRAMES,
                          session_date=SESSION, now_et_seconds=_sealed_seconds())
    assert out["written"] == 1
    assert out["excursions_inserted"] == 1
    sid = D.unlabelled_samples(SESSION)[0]
    exc = S.get_sample_excursions([sid])
    assert sid in exc
    assert exc[sid]["samples"] == 1
    assert exc[sid]["identity_basis"] == "CANONICAL_FEATURE_SAMPLE_ID"
    health = S.sample_excursion_health()
    assert health["sample_excursions"] == 1
    assert health["capture"]["excursions_inserted"] == 1
    assert health["capture"]["capture_errors"] == 0


def test_existing_feature_widens_same_canonical_excursion(monkeypatch):
    _init(monkeypatch)
    first = W.write_samples(priced_clusters=[_cluster(pl=100.0)], replay_rows=FRAMES,
                            session_date=SESSION, now_et_seconds=_sealed_seconds())
    second = W.write_samples(priced_clusters=[_cluster(pl=1500.0)], replay_rows=FRAMES,
                             session_date=SESSION, now_et_seconds=_sealed_seconds()+60)
    assert first["excursions_inserted"] == 1
    assert second["already_present"] == 1
    assert second["excursions_updated"] == 1
    sid = D.unlabelled_samples(SESSION)[0]
    exc = S.get_sample_excursions([sid])[sid]
    assert exc["samples"] == 2
    assert exc["mfe_dollars"] == 1500.0
    assert exc["mae_dollars"] == 100.0
    health = S.sample_excursion_health()
    assert health["capture"]["excursions_updated"] == 1


def test_no_feature_means_no_orphan_excursion(monkeypatch):
    _init(monkeypatch)
    # No replay frame exists at/before this 09:31 decision, so no feature may be frozen.
    cl = _cluster()
    cl["end_time"] = "09:31:11"
    out = W.write_samples(priced_clusters=[cl], replay_rows=FRAMES,
                          session_date=SESSION, now_et_seconds=10*3600)
    assert out["written"] == 0
    assert out["no_frame"] == 1
    assert S.sample_excursion_health()["sample_excursions"] == 0


def test_missing_real_pl_is_observed_not_fabricated(monkeypatch):
    _init(monkeypatch)
    cl = _cluster()
    cl["_excursion_observation"]["pl_dollars"] = None
    out = W.write_samples(priced_clusters=[cl], replay_rows=FRAMES,
                          session_date=SESSION, now_et_seconds=_sealed_seconds())
    assert out["written"] == 1
    assert out["excursion_missing_pl"] == 1
    assert out["excursions_inserted"] == 0
    health = S.sample_excursion_health()
    assert health["sample_excursions"] == 0
    assert health["capture"]["missing_pl"] == 1
