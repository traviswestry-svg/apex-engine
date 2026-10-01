import json
from pathlib import Path
from engine import flow_pl_store


def _use_db(monkeypatch, tmp_path):
    db = tmp_path / "tracking.db"
    monkeypatch.setattr(flow_pl_store, "_DB_PATH", str(db))
    assert flow_pl_store.init_db()
    return db


def test_release_truth_and_handoff_guardrails():
    d = json.loads(Path("config/apex_release_manifest.json").read_text())
    assert d["apex_version"] == d["semantic_version"] == d["application_version"] == "69.10.27"
    assert d["build_name"] == "Expected Range Reversal Timing Intelligence"
    g = d["guardrails"]
    assert g["canonical_feature_pl_handoff_audit"] is True
    assert g["canonical_feature_pl_handoff_exact_tuple_only"] is True
    assert g["canonical_feature_pl_handoff_reconstructs_identity"] is False
    assert g["canonical_feature_pl_handoff_fuzzy_matching"] is False
    assert g["canonical_feature_pl_handoff_writes_evidence"] is False
    assert g["canonical_feature_pl_handoff_historical_backfill"] is False


def test_handoff_audit_records_exact_owner_found_and_missing(monkeypatch, tmp_path):
    _use_db(monkeypatch, tmp_path)
    assert flow_pl_store.record_feature_pl_handoff_observation(
        session_date="2026-09-28", legacy_cluster_key="SPX|CALL|2026-09-28|BULLISH",
        decision_time="2026-09-28T10:00:00", exact_owner_sample_id="s_exact")
    assert flow_pl_store.record_feature_pl_handoff_observation(
        session_date="2026-09-28", legacy_cluster_key="SPX|PUT|2026-09-28|BEARISH",
        decision_time="2026-09-28T10:01:00", exact_owner_sample_id=None)
    h = flow_pl_store.feature_pl_handoff_health()
    assert h["pl_handoff_observations"] == 2
    assert h["exact_feature_owner_found"] == 1
    assert h["exact_feature_owner_missing"] == 1
    assert h["exact_owner_resolution_pct"] == 50.0
    assert h["by_direction"]["BULLISH"]["owner_found"] == 1
    assert h["by_direction"]["BEARISH"]["owner_missing"] == 1
    assert h["writes_evidence"] is False
    assert h["reconstructs_identity"] is False
    assert h["fuzzy_matching"] is False


def test_handoff_audit_does_not_create_identity_or_excursion(monkeypatch, tmp_path):
    _use_db(monkeypatch, tmp_path)
    assert flow_pl_store.record_feature_pl_handoff_observation(
        session_date="2026-09-28", legacy_cluster_key="SPX|CALL|2026-10-02|BULLISH",
        decision_time="2026-09-28T11:00:00", exact_owner_sample_id=None)
    assert flow_pl_store.resolve_exact_sample_identity(
        session_date="2026-09-28", legacy_cluster_key="SPX|CALL|2026-10-02|BULLISH",
        decision_time="2026-09-28T11:00:00") is None
    assert flow_pl_store.get_sample_excursions(["s_any"]) == {}


def test_sample_excursion_health_exposes_handoff(monkeypatch, tmp_path):
    _use_db(monkeypatch, tmp_path)
    flow_pl_store.record_feature_pl_handoff_observation(
        session_date="2026-09-28", legacy_cluster_key="SPX|PUT|2026-09-28|BEARISH",
        decision_time="2026-09-28T12:00:00", exact_owner_sample_id=None)
    h = flow_pl_store.sample_excursion_health()
    assert h["feature_pl_handoff"]["version"] == "69.10.23"
    assert h["feature_pl_handoff"]["exact_feature_owner_missing"] == 1
