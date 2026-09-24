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
    assert d["apex_version"] == d["semantic_version"] == d["application_version"] == "69.10.22"
    assert d["build_name"] == "Canonical Feature Sample Excursion Ownership Closure"
    g = d["guardrails"]
    assert g["canonical_feature_sample_excursion_ownership_required"] is True
    assert g["canonical_excursion_write_requires_registered_owner"] is True
    assert g["canonical_pending_outcome_audit_writes_evidence"] is False
    assert g["canonical_pending_outcome_reconstructs_identity"] is False
    assert g["canonical_pending_outcome_fuzzy_matching"] is False
    assert g["canonical_pending_outcome_synthetic_pl"] is False


def test_canonical_write_requires_exact_registered_owner(monkeypatch, tmp_path):
    _use_db(monkeypatch, tmp_path)
    session = "2026-09-24"
    dt = f"{session}T10:00:00"
    assert flow_pl_store.register_sample_identity(sample_id="s_owner", session_date=session,
        legacy_cluster_key="K1", decision_time=dt)
    ok = flow_pl_store.record_sample_excursion(sample_id="s_owner", session_date=session,
        ticker="SPX", pl_dollars=10.0, cost_basis=100.0, decision_time=dt,
        legacy_cluster_key="K1", require_registered_owner=True)
    assert ok and ok["readback_verified"] is True
    refused = flow_pl_store.record_sample_excursion(sample_id="s_owner", session_date=session,
        ticker="SPX", pl_dollars=20.0, cost_basis=100.0, decision_time=dt,
        legacy_cluster_key="K2", require_registered_owner=True)
    assert refused is None
    row = flow_pl_store.get_sample_excursions(["s_owner"])["s_owner"]
    assert row["samples"] == 1


def test_unregistered_canonical_write_fails_closed(monkeypatch, tmp_path):
    _use_db(monkeypatch, tmp_path)
    cap = flow_pl_store.record_sample_excursion(sample_id="s_orphan", session_date="2026-09-24",
        ticker="SPX", pl_dollars=10.0, cost_basis=100.0,
        decision_time="2026-09-24T10:01:00", legacy_cluster_key="K",
        require_registered_owner=True)
    assert cap is None
    assert "s_orphan" not in flow_pl_store.get_sample_excursions(["s_orphan"])


def test_pending_outcome_audit_distinguishes_missing_pl_from_integrity_failure(monkeypatch, tmp_path):
    _use_db(monkeypatch, tmp_path)
    session = "2026-09-24"
    dt1, dt2 = f"{session}T10:02:00", f"{session}T10:03:00"
    assert flow_pl_store.register_sample_identity(sample_id="s_wait", session_date=session,
        legacy_cluster_key="WAIT", decision_time=dt1)
    assert flow_pl_store.record_sample_pl_lifecycle(sample_id="s_wait", session_date=session,
        legacy_cluster_key="WAIT", decision_time=dt1, state="AWAITING_REAL_PL", reason="NO_REAL_PL")
    assert flow_pl_store.register_sample_identity(sample_id="s_bad", session_date=session,
        legacy_cluster_key="BAD", decision_time=dt2)
    assert flow_pl_store.record_sample_pl_lifecycle(sample_id="s_bad", session_date=session,
        legacy_cluster_key="BAD", decision_time=dt2, state="PL_OBSERVED_EXCURSION_WRITTEN",
        reason="SIMULATED_MISSING_ROW", pl_observed=True, excursion_written=True)
    r = flow_pl_store.audit_pending_sample_outcome_eligibility(
        ["s_wait", "s_bad", "s_legacy"], session_date=session)
    assert r["pending_sample_ids"] == 3
    assert r["registered_identity"] == 2
    assert r["awaiting_real_pl"] == 1
    assert r["excursion_state_without_excursion"] == 1
    assert r["feature_only_unregistered"] == 1
    assert r["ownership_integrity_failures"] == 1
    assert r["state"] == "OWNERSHIP_INTEGRITY_FAILURE"
    assert r["writes_evidence"] is False
    assert r["reconstructs_identity"] is False
    assert r["fuzzy_matching"] is False
