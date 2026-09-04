import json
import tempfile
from pathlib import Path

from engine import feature_store_db as D
from engine import flow_pl_store as S
from engine import feature_store_writer as W

SESSION = "2026-09-03"
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


def _cluster(pl=125.0):
    key = "SPX|CALL|2026-09-03|BULLISH"
    return {
        "ticker": "SPX",
        "option_type": "CALL",
        "expiration": "2026-09-03",
        "directional_interpretation": "BULLISH",
        "cluster_key": {
            "ticker": "SPX",
            "option_type": "CALL",
            "expiration": "2026-09-03",
            "directional_interpretation": "BULLISH",
        },
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
            "cost_basis": 1000.0,
            "ticker": "SPX",
            "legacy_cluster_key": key,
        },
    }


def test_release_truth_6999():
    manifest = json.loads(Path("config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"] == "69.10.1"
    assert manifest["build_name"] == "Scanner Lifecycle & Flow Excursion Capture Closure"
    g = manifest["guardrails"]
    assert g["live_flow_excursion_capture_owned_by_feature_writer"] is True
    assert g["live_flow_excursion_capture_deferred_in_production"] is False
    assert g["live_flow_excursion_capture_post_feature_persistence"] is True
    assert g["live_flow_excursion_capture_uses_canonical_sample_id_only"] is True
    assert g["live_flow_excursion_backfills_history"] is False
    assert g["live_flow_excursion_synthetic_pl_allowed"] is False
    assert g["live_flow_excursion_changes_trade_decisions"] is False
    assert g["live_flow_excursion_changes_execution_authority"] is False

    registry = Path("config/apex_capability_registry.yaml").read_text()
    assert "apex_version: 69.10.1" in registry
    assert 'live_flow_excursion_invocation_closure:' in registry
    assert 'version: "69.10.1"' in registry
    assert "feature_writer_owned_capture" in registry
    assert "production_defer_disabled" in registry


def test_default_writer_path_captures_excursion_after_feature_persistence(monkeypatch):
    _init(monkeypatch)
    rep = W.write_samples(
        priced_clusters=[_cluster(125.0)],
        replay_rows=FRAMES,
        session_date=SESSION,
        now_et_seconds=10 * 3600 + 35 * 60,
    )
    assert rep["written"] == 1
    assert rep["excursion_capture_deferred"] is False
    assert rep["excursion_capture_attempts"] == 1
    assert rep["excursions_inserted"] == 1
    assert rep["excursion_capture_errors"] == 0
    assert rep["capture_targets"] == []

    health = S.sample_excursion_health()
    assert health["capture"]["capture_attempts"] == 1
    assert health["capture"]["excursions_inserted"] == 1
    assert health["sample_excursions"] == 1


def test_existing_feature_updates_same_canonical_excursion(monkeypatch):
    _init(monkeypatch)
    first = W.write_samples(
        priced_clusters=[_cluster(100.0)],
        replay_rows=FRAMES,
        session_date=SESSION,
        now_et_seconds=10 * 3600 + 35 * 60,
    )
    assert first["excursions_inserted"] == 1

    second = W.write_samples(
        priced_clusters=[_cluster(900.0)],
        replay_rows=FRAMES,
        session_date=SESSION,
        now_et_seconds=10 * 3600 + 36 * 60,
    )
    assert second["already_present"] == 1
    assert second["excursion_capture_attempts"] == 1
    assert second["excursions_updated"] == 1

    health = S.sample_excursion_health()
    assert health["capture"]["capture_attempts"] == 2
    assert health["capture"]["excursions_inserted"] == 1
    assert health["capture"]["excursions_updated"] == 1


def test_missing_live_pl_is_observed_not_fabricated(monkeypatch):
    _init(monkeypatch)
    rep = W.write_samples(
        priced_clusters=[_cluster(None)],
        replay_rows=FRAMES,
        session_date=SESSION,
        now_et_seconds=10 * 3600 + 35 * 60,
    )
    assert rep["written"] == 1
    assert rep["excursion_capture_attempts"] == 1
    assert rep["excursion_missing_pl"] == 1
    assert rep["excursions_inserted"] == 0
    assert S.sample_excursion_health()["sample_excursions"] == 0


def test_production_scanner_uses_non_deferred_writer_capture():
    src = Path("app.py").read_text()
    assert "defer_excursion_capture=False" in src
    assert "defer_excursion_capture=True)" not in src
    assert "feature writer itself" in src
    assert "_rep['excursion_capture_attempts']" in src
