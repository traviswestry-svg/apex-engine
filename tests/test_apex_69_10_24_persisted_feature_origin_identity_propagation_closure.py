import json
from pathlib import Path

import pytest

from engine import flow_pl_store, feature_store_db


@pytest.fixture()
def stores(monkeypatch, tmp_path):
    db = tmp_path / "apex_69_10_24.db"
    monkeypatch.setattr(flow_pl_store, "_DB_PATH", str(db))
    monkeypatch.setattr(feature_store_db, "_DB_PATH", str(db))
    monkeypatch.setattr(flow_pl_store, "_DB_READY", False)
    monkeypatch.setattr(feature_store_db, "_DB_READY", False)
    assert feature_store_db.init_db()
    assert flow_pl_store.init_db()
    return db


def test_release_truth_capability_and_guardrails():
    m = json.loads(Path("config/apex_release_manifest.json").read_text())
    assert m["apex_version"] == m["semantic_version"] == m["application_version"] == "69.10.33"
    assert m["build_name"] == "Session Calendar Integrity Closure"
    g = m["guardrails"]
    assert g["persisted_feature_origin_identity_propagation_closure"] is True
    assert g["immutable_origin_provenance"] is True
    assert g["origin_exact_registered_owner_required"] is True
    assert g["origin_genuine_pl_required"] is True
    assert g["origin_fuzzy_matching"] is False
    assert g["origin_reconstructs_identity"] is False
    assert g["origin_historical_backfill"] is False
    registry = Path("config/apex_capability_registry.yaml").read_text()
    assert "persisted_feature_origin_identity_propagation_closure:" in registry
    assert "version: 69.10.25" in registry
    assert "identity_basis: CANONICAL_FEATURE_SAMPLE_ID" in registry


def _register_origin(sample_id, direction, event_ids):
    session = "2026-09-29"
    key = f"SPX|CALL|2026-10-02|{direction}"
    dt = f"{session}T10:15:00"
    assert flow_pl_store.register_sample_identity(
        sample_id=sample_id, session_date=session, legacy_cluster_key=key,
        decision_time=dt, origin_event_ids=event_ids)
    return session, key, dt


def test_origin_propagation_is_immutable_across_uncertain_to_bullish(stores):
    session, original_key, original_dt = _register_origin("s_bull", "UNCERTAIN", ["e1", "e2"])
    origin = flow_pl_store.resolve_feature_origin_provenance(event_ids=["e1", "e2"])
    assert origin == {"sample_id": "s_bull", "session_date": session,
                      "legacy_cluster_key": original_key, "decision_time": original_dt}
    assert flow_pl_store.verify_sample_identity_owner(**origin)
    current_key = "SPX|CALL|2026-10-02|BULLISH"
    cap = flow_pl_store.record_sample_excursion(
        sample_id=origin["sample_id"], session_date=origin["session_date"], ticker="SPX",
        pl_dollars=125.0, cost_basis=500.0, decision_time=origin["decision_time"],
        legacy_cluster_key=origin["legacy_cluster_key"], require_registered_owner=True)
    assert cap and cap["sample_id"] == "s_bull"
    row = flow_pl_store.get_sample_excursions(["s_bull"])["s_bull"]
    assert row["legacy_cluster_key"] == original_key
    assert row["decision_time"] == original_dt
    assert flow_pl_store.record_feature_origin_pl_observation(
        observation_session_date=session, observation_legacy_cluster_key=current_key,
        observation_decision_time=original_dt, origin=origin, owner_validated=True,
        diagnostic_reason="ORIGIN_OWNER_VALIDATED", excursion_written=True)
    h = flow_pl_store.feature_origin_provenance_health(session)
    assert h["origin_provenance_present"] == 1
    assert h["origin_owner_validated"] == 1
    assert h["origin_direction_evolved"] == 1
    assert h["origin_uncertain_to_bullish"] == 1
    assert h["origin_owned_excursion_writes"] == 1


def test_origin_propagation_uncertain_to_bearish(stores):
    session, _, dt = _register_origin("s_bear", "UNCERTAIN", ["e3"])
    origin = flow_pl_store.resolve_feature_origin_provenance(event_ids=["e3"])
    assert flow_pl_store.record_feature_origin_pl_observation(
        observation_session_date=session,
        observation_legacy_cluster_key="SPX|CALL|2026-10-02|BEARISH",
        observation_decision_time=dt, origin=origin, owner_validated=True,
        diagnostic_reason="ORIGIN_OWNER_VALIDATED")
    h = flow_pl_store.feature_origin_provenance_health(session)
    assert h["origin_uncertain_to_bearish"] == 1


def test_missing_provenance_does_not_reconstruct_owner(stores):
    session, key, dt = _register_origin("s_existing", "BULLISH", ["bound-event"])
    # Same market attributes and time are intentionally irrelevant without the
    # originating event binding.
    assert flow_pl_store.resolve_feature_origin_provenance(event_ids=["unbound-event"]) is None
    exact = flow_pl_store.resolve_exact_sample_identity(
        session_date=session, legacy_cluster_key=key, decision_time=dt)
    assert exact and exact["sample_id"] == "s_existing"  # diagnostic path still exists
    assert flow_pl_store.get_sample_excursions(["s_existing"]) == {}
    assert flow_pl_store.record_feature_origin_pl_observation(
        observation_session_date=session, observation_legacy_cluster_key=key,
        observation_decision_time=dt, origin=None, owner_validated=False,
        diagnostic_reason="ORIGIN_PROVENANCE_MISSING")
    h = flow_pl_store.feature_origin_provenance_health(session)
    assert h["origin_provenance_missing"] == 1
    assert h["origin_owned_pl_observations"] == 0


def test_owner_tuple_mismatch_fails_closed(stores):
    session, key, dt = _register_origin("s_mismatch", "UNCERTAIN", ["e4"])
    origin = flow_pl_store.resolve_feature_origin_provenance(event_ids=["e4"])
    bad = dict(origin)
    bad["legacy_cluster_key"] = "SPX|CALL|2026-10-02|BULLISH"
    assert not flow_pl_store.verify_sample_identity_owner(**bad)
    assert flow_pl_store.record_sample_excursion(
        sample_id=bad["sample_id"], session_date=bad["session_date"], ticker="SPX",
        pl_dollars=50.0, cost_basis=100.0, decision_time=bad["decision_time"],
        legacy_cluster_key=bad["legacy_cluster_key"], require_registered_owner=True) is None
    assert flow_pl_store.get_sample_excursions(["s_mismatch"]) == {}
    assert flow_pl_store.record_feature_origin_pl_observation(
        observation_session_date=session, observation_legacy_cluster_key=key,
        observation_decision_time=dt, origin=bad, owner_validated=False,
        diagnostic_reason="ORIGIN_OWNER_VALIDATION_FAILED")
    h = flow_pl_store.feature_origin_provenance_health(session)
    assert h["origin_owner_validation_failed"] == 1
    assert h["ownership_integrity_failures"] == 1


def test_genuine_pl_required_and_write_readback_preserved(stores):
    session, key, dt = _register_origin("s_realpl", "UNCERTAIN", ["e5"])
    origin = flow_pl_store.resolve_feature_origin_provenance(event_ids=["e5"])
    assert flow_pl_store.record_sample_excursion(
        sample_id=origin["sample_id"], session_date=session, ticker="SPX",
        pl_dollars=None, cost_basis=100.0, decision_time=dt,
        legacy_cluster_key=key, require_registered_owner=True) is None
    assert flow_pl_store.get_sample_excursions(["s_realpl"]) == {}
    cap = flow_pl_store.record_sample_excursion(
        sample_id=origin["sample_id"], session_date=session, ticker="SPX",
        pl_dollars=-25.0, cost_basis=100.0, decision_time=dt,
        legacy_cluster_key=key, require_registered_owner=True)
    assert cap
    assert "s_realpl" in flow_pl_store.get_sample_excursions(["s_realpl"])
    rb = flow_pl_store.excursion_write_readback_health()
    assert rb["readback_verified"] == 1
    assert rb["readback_missing"] == 0
    assert rb["readback_identity_mismatch"] == 0


def test_conflicting_event_origin_registration_fails_closed(stores):
    session, _, _ = _register_origin("s_one", "UNCERTAIN", ["shared-event"])
    assert not flow_pl_store.register_sample_identity(
        sample_id="s_two", session_date=session,
        legacy_cluster_key="SPX|CALL|2026-10-02|BULLISH",
        decision_time=f"{session}T10:20:00", origin_event_ids=["shared-event"])
    origin = flow_pl_store.resolve_feature_origin_provenance(event_ids=["shared-event"])
    assert origin["sample_id"] == "s_one"
