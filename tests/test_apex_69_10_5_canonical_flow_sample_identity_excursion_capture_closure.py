import json
import tempfile
from pathlib import Path

from engine import feature_store_db as D
from engine import flow_pl_store as S
from engine import feature_store_writer as W
from engine import storage_retention

SESSION = "2026-09-11"
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


def _cluster(*, end_time="10:31:11", pl=125.0, direction="BULLISH"):
    key = f"SPX|CALL|{SESSION}|{direction}"
    return {
        "ticker": "SPX",
        "option_type": "CALL",
        "expiration": SESSION,
        "directional_interpretation": direction,
        "cluster_key": {
            "ticker": "SPX", "option_type": "CALL", "expiration": SESSION,
            "directional_interpretation": direction,
        },
        "cluster_key_string": key,
        "start_time": "10:31:02",
        "end_time": end_time,
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


def test_release_truth_and_guardrails():
    manifest = json.loads(Path("config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"] == "69.10.16"
    assert manifest["build_name"] == "Canonical Settlement Identity & Decision Gamma Linkage Closure"
    g = manifest["guardrails"]
    assert g["flow_source_stage_canonical_excursion_capture_allowed"] is False
    assert g["flow_source_stage_missing_feature_counts_as_capture_failure"] is False
    assert g["canonical_flow_capture_requires_exact_persisted_feature_lookup"] is True
    assert g["canonical_flow_identity_registration_verified_before_capture"] is True
    assert g["canonical_flow_capture_candidate_skips_separated_from_capture_failures"] is True
    assert g["storage_capacity_automatic_cleanup"] is False

    registry = Path("config/apex_capability_registry.yaml").read_text()
    assert "apex_version: 69.10.16" in registry
    assert 'version: "69.10.5"' in registry
    assert "source_stage_capture_forbidden" in registry
    assert "pre_persistence_skips_not_capture_failures" in registry


def test_source_stage_pipeline_no_longer_attempts_canonical_capture():
    src = Path("engine/flow_pl_pipeline.py").read_text()
    start = src.index("APEX 69.10.5: this source-stage pipeline MUST NOT attempt canonical")
    end = src.index("sources.append(src)", start)
    block = src[start:end]
    assert "record_sample_excursion(" not in block
    assert "record_capture_audit(" not in block
    assert "resolve_sample_identity(" not in block
    assert "make_sample_id" not in block


def test_replay_frame_rejection_is_pre_persistence_skip_not_capture_failure(monkeypatch):
    _init(monkeypatch)
    cl = _cluster(end_time="09:31:11", pl=250.0)
    out = W.write_samples(
        priced_clusters=[cl], replay_rows=FRAMES, session_date=SESSION,
        now_et_seconds=10 * 3600,
    )
    assert out["written"] == 0
    assert out["skipped_before_persist_no_frame"] == 1
    assert out["excursion_capture_attempts"] == 0
    health = S.sample_excursion_health()
    assert health["capture"]["capture_attempts"] == 0
    assert health["capture"]["missing_feature_sample"] == 0
    assert health["capture"]["canonical_capture_attempts"] == 0
    assert health["capture"]["canonical_missing_feature_sample"] == 0


def test_exact_persisted_sample_is_registered_then_captured(monkeypatch):
    _init(monkeypatch)
    out = W.write_samples(
        priced_clusters=[_cluster(pl=125.0)], replay_rows=FRAMES,
        session_date=SESSION, now_et_seconds=10 * 3600 + 35 * 60,
    )
    assert out["written"] == 1
    assert out["canonical_lookup_missing"] == 0
    assert out["identity_registration_failures"] == 0
    assert out["excursion_capture_attempts"] == 1
    assert out["excursions_inserted"] == 1
    sid = D.unlabelled_samples(SESSION)[0]
    assert D.get_features(sid) is not None
    identity = S.resolve_sample_identity(
        session_date=SESSION,
        legacy_cluster_key=f"SPX|CALL|{SESSION}|BULLISH",
    )
    assert identity["sample_id"] == sid
    health = S.sample_excursion_health()
    assert health["capture_owner"] == "FEATURE_STORE_WRITER_POST_PERSISTENCE"
    assert health["capture"]["canonical_capture_attempts"] == 1
    assert health["capture"]["canonical_missing_feature_sample"] == 0
    assert health["capture"]["excursions_inserted"] == 1


def test_identity_registration_collision_fails_closed(monkeypatch):
    _init(monkeypatch)
    # First lineage row owns the sample id.
    assert S.register_sample_identity(
        sample_id="s_collision", session_date=SESSION,
        legacy_cluster_key="A", decision_time=f"{SESSION}T10:00:00")
    # The same sample_id cannot silently claim a different lineage.
    assert not S.register_sample_identity(
        sample_id="s_collision", session_date=SESSION,
        legacy_cluster_key="B", decision_time=f"{SESSION}T10:01:00")


def test_runtime_telemetry_separates_pl_observations_from_feature_samples():
    src = Path("app.py").read_text()
    assert '"version": "69.10.6"' in src
    assert '"flow_pl_observations_recorded": 0' in src
    assert '"skipped_before_persist_no_frame": 0' in src
    assert '"canonical_lookup_missing": 0' in src
    assert '"identity_registration_failures": 0' in src
    assert '"PRE_PERSIST_REPLAY_FRAME_GATED"' in src
    assert '"CANONICAL_FEATURE_LOOKUP_MISSING"' in src


def test_storage_capacity_warning_is_read_only(monkeypatch, tmp_path):
    monkeypatch.setattr(storage_retention, "storage_status", lambda: {"free_pct": 19.29})
    monkeypatch.setattr(storage_retention, "DEFAULT_DB", str(tmp_path / "missing.db"))
    out = storage_retention.audit(root=tmp_path)
    assert out["storage_capacity"]["state"] == "WARNING"
    assert out["storage_capacity"]["operator_action_required"] is True
    assert out["storage_capacity"]["automatic_cleanup"] is False
    assert out["guardrails"]["automatic_delete"] is False
    assert out["guardrails"]["capacity_warning_observational_only"] is True
