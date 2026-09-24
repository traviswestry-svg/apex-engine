import json
from pathlib import Path

from engine import flow_pl_store


def _use_db(monkeypatch, tmp_path):
    db = tmp_path / "tracking.db"
    monkeypatch.setattr(flow_pl_store, "_DB_PATH", str(db))
    assert flow_pl_store.init_db()
    return db


def test_release_truth_and_guardrails():
    d = json.loads(Path("config/apex_release_manifest.json").read_text())
    assert d["apex_version"] == "69.10.21"
    assert d["build_name"] == "Canonical Settlement Cohort Identity Reconciliation"
    g = d["guardrails"]
    assert g["canonical_settlement_cohort_exact_sample_id_only"] is True
    assert g["canonical_settlement_cohort_writes_evidence"] is False
    assert g["canonical_settlement_cohort_reconstructs_identity"] is False
    assert g["canonical_settlement_cohort_fuzzy_matching"] is False
    assert g["canonical_settlement_cohort_historical_backfill"] is False


def test_exact_cohort_reconciliation_exposes_both_set_differences(monkeypatch, tmp_path):
    _use_db(monkeypatch, tmp_path)
    session = "2026-09-24"
    # Requested + persisted excursion.
    flow_pl_store.register_sample_identity(sample_id="s_shared", session_date=session,
        legacy_cluster_key="K1", decision_time=f"{session}T10:00:00")
    assert flow_pl_store.record_sample_excursion(sample_id="s_shared", session_date=session,
        ticker="SPX", pl_dollars=10.0, cost_basis=100.0,
        legacy_cluster_key="K1", decision_time=f"{session}T10:00:00")
    # Requested + identity map, but no excursion.
    flow_pl_store.register_sample_identity(sample_id="s_requested_only", session_date=session,
        legacy_cluster_key="K2", decision_time=f"{session}T10:01:00")
    # Persisted excursion that settlement did not request.
    flow_pl_store.register_sample_identity(sample_id="s_excursion_only", session_date=session,
        legacy_cluster_key="K3", decision_time=f"{session}T10:02:00")
    assert flow_pl_store.record_sample_excursion(sample_id="s_excursion_only", session_date=session,
        ticker="SPX", pl_dollars=20.0, cost_basis=100.0,
        legacy_cluster_key="K3", decision_time=f"{session}T10:02:00")

    r = flow_pl_store.reconcile_settlement_excursion_cohort(
        ["s_shared", "s_requested_only", "s_feature_only"], session_date=session)
    assert r["settlement_requested_ids"] == 3
    assert r["excursion_session_ids"] == 2
    assert r["requested_with_excursion"] == 1
    assert r["requested_without_excursion"] == 2
    assert r["excursion_not_requested"] == 1
    assert r["identity_map_only_requested"] == 1
    assert r["feature_only_requested"] == 1
    assert r["state"] == "EXACT_COHORT_DIVERGENCE"
    assert r["writes_evidence"] is False
    assert r["reconstructs_identity"] is False
    assert r["fuzzy_matching"] is False


def test_reconciliation_is_session_scoped_and_does_not_recover_by_tuple(monkeypatch, tmp_path):
    _use_db(monkeypatch, tmp_path)
    assert flow_pl_store.record_sample_excursion(sample_id="s_other", session_date="2026-09-23",
        ticker="SPX", pl_dollars=5.0, cost_basis=100.0,
        legacy_cluster_key="SAME", decision_time="2026-09-23T10:00:00")
    r = flow_pl_store.reconcile_settlement_excursion_cohort(
        ["s_missing"], session_date="2026-09-24")
    assert r["requested_with_excursion"] == 0
    assert r["excursion_session_ids"] == 0
    assert r["requested_without_excursion"] == 1
