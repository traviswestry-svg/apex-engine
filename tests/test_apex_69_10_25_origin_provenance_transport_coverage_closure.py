import json
from pathlib import Path

import pytest

from engine import flow_pl_store, feature_store_db


@pytest.fixture()
def stores(monkeypatch, tmp_path):
    db = tmp_path / "apex_69_10_25.db"
    monkeypatch.setattr(flow_pl_store, "_DB_PATH", str(db))
    monkeypatch.setattr(feature_store_db, "_DB_PATH", str(db))
    monkeypatch.setattr(flow_pl_store, "_DB_READY", False)
    monkeypatch.setattr(feature_store_db, "_DB_READY", False)
    assert feature_store_db.init_db()
    assert flow_pl_store.init_db()
    return db


def reg(sample_id, event_ids, direction="UNCERTAIN", t="10:15:00"):
    session = "2026-09-30"
    key = f"SPX|CALL|2026-10-02|{direction}"
    dt = f"{session}T{t}"
    assert flow_pl_store.register_sample_identity(
        sample_id=sample_id, session_date=session, legacy_cluster_key=key,
        decision_time=dt, origin_event_ids=event_ids)
    return {"sample_id": sample_id, "session_date": session,
            "legacy_cluster_key": key, "decision_time": dt}


def test_release_truth_and_capability():
    m = json.loads(Path("config/apex_release_manifest.json").read_text())
    assert m["apex_version"] == m["semantic_version"] == m["application_version"] == "69.10.33"
    assert m["build_name"] == "Session Calendar Integrity Closure"
    assert m["database_schema_version"] == "8"
    g = m["guardrails"]
    assert g["origin_provenance_transport_coverage_closure"] is True
    assert g["origin_partial_consistent_event_ancestry_allowed"] is True
    assert g["origin_conflicting_bound_ancestors_fail_closed"] is True
    assert g["origin_transport_uses_market_attributes"] is False
    registry = Path("config/apex_capability_registry.yaml").read_text()
    assert "origin_provenance_transport_coverage_closure:" in registry
    assert "identity_basis: DIRECT_CONTINUING_EVENT_ANCESTRY_ONLY" in registry


def test_full_exact_binding_remains_authorized(stores):
    expected = reg("s_full", ["e1", "e2"])
    r = flow_pl_store.resolve_feature_origin_transport(event_ids=["e1", "e2"])
    assert r["transport_status"] == "FULL_EXACT_BINDING"
    assert r["owner_authorized"] is True
    assert r["origin"] == expected
    assert flow_pl_store.verify_sample_identity_owner(**r["origin"])


def test_partial_consistent_ancestry_closes_added_member_gap(stores):
    expected = reg("s_partial", ["e10", "e11"])
    # e12 is a newly-added member in the later rebuilt cluster. It is not used
    # to infer ownership; direct continuing ancestry comes from e10/e11.
    r = flow_pl_store.resolve_feature_origin_transport(event_ids=["e10", "e11", "e12"])
    assert r["transport_status"] == "PARTIAL_CONSISTENT_BINDING"
    assert r["bound_event_count"] == 2
    assert r["unbound_event_count"] == 1
    assert r["origin"] == expected
    assert flow_pl_store.verify_sample_identity_owner(**r["origin"])
    cap = flow_pl_store.record_sample_excursion(
        sample_id=expected["sample_id"], session_date=expected["session_date"], ticker="SPX",
        pl_dollars=75.0, cost_basis=200.0, decision_time=expected["decision_time"],
        legacy_cluster_key=expected["legacy_cluster_key"], require_registered_owner=True)
    assert cap and cap["sample_id"] == "s_partial"


def test_no_bound_events_fail_closed_without_attribute_fallback(stores):
    reg("s_known", ["bound"])
    r = flow_pl_store.resolve_feature_origin_transport(event_ids=["new-a", "new-b"])
    assert r["transport_status"] == "NO_BOUND_EVENTS"
    assert r["owner_authorized"] is False
    assert r["origin"] is None
    assert r["uses_market_attributes"] is False
    assert flow_pl_store.resolve_feature_origin_provenance(event_ids=["new-a", "new-b"]) is None


def test_no_event_ids_are_reason_coded_and_fail_closed(stores):
    r = flow_pl_store.resolve_feature_origin_transport(event_ids=[])
    assert r["transport_status"] == "NO_EVENT_IDS"
    assert r["owner_authorized"] is False


def test_conflicting_bound_origins_fail_closed(stores):
    reg("s_a", ["ea"], t="10:15:00")
    reg("s_b", ["eb"], t="10:16:00")
    r = flow_pl_store.resolve_feature_origin_transport(event_ids=["ea", "eb", "new"])
    assert r["transport_status"] == "CONFLICTING_BOUND_ORIGINS"
    assert r["distinct_bound_origins"] == 2
    assert r["owner_authorized"] is False
    assert r["origin"] is None


def test_exact_registered_owner_still_required(stores):
    expected = reg("s_owner", ["owner-event"])
    r = flow_pl_store.resolve_feature_origin_transport(event_ids=["owner-event", "new"])
    assert r["owner_authorized"]
    bad = dict(r["origin"])
    bad["decision_time"] = "2026-09-30T10:15:01"
    assert not flow_pl_store.verify_sample_identity_owner(**bad)
    assert flow_pl_store.record_sample_excursion(
        sample_id=bad["sample_id"], session_date=bad["session_date"], ticker="SPX",
        pl_dollars=20.0, cost_basis=100.0, decision_time=bad["decision_time"],
        legacy_cluster_key=bad["legacy_cluster_key"], require_registered_owner=True) is None
    assert flow_pl_store.get_sample_excursions([expected["sample_id"]]) == {}


def test_transport_coverage_audit_distinguishes_reasons(stores):
    origin = reg("s_cov", ["c1", "c2"])
    cases = [
        (["c1", "c2"], "FULL_EXACT_BINDING"),
        (["c1", "c2", "c3"], "PARTIAL_CONSISTENT_BINDING"),
        (["none"], "NO_BOUND_EVENTS"),
        ([], "NO_EVENT_IDS"),
    ]
    for i, (ids, status) in enumerate(cases):
        r = flow_pl_store.resolve_feature_origin_transport(event_ids=ids)
        assert r["transport_status"] == status
        assert flow_pl_store.record_feature_origin_transport_observation(
            observation_session_date=origin["session_date"],
            observation_legacy_cluster_key=f"SPX|CALL|2026-10-02|BULLISH{i}",
            observation_decision_time=f"2026-09-30T10:2{i}:00", transport=r)
    h = flow_pl_store.feature_origin_transport_coverage_health("2026-09-30")
    assert h["transport_observations"] == 4
    assert h["full_exact_bindings"] == 1
    assert h["partial_consistent_bindings"] == 1
    assert h["no_bound_events"] == 1
    assert h["no_event_ids"] == 1
    assert h["transport_owner_resolved"] == 2
    assert h["transport_owner_missing"] == 2
    assert h["transport_resolution_pct"] == 50.0
    assert h["fuzzy_matching"] is False
    assert h["reconstructs_identity"] is False
    assert h["latest_owner_substitution"] is False


def test_direction_change_does_not_change_original_owner(stores):
    original = reg("s_direction", ["d1", "d2"], direction="UNCERTAIN")
    r = flow_pl_store.resolve_feature_origin_transport(event_ids=["d1", "d2", "d3"])
    assert r["origin"] == original
    assert flow_pl_store.record_feature_origin_pl_observation(
        observation_session_date="2026-09-30",
        observation_legacy_cluster_key="SPX|CALL|2026-10-02|BEARISH",
        observation_decision_time="2026-09-30T10:30:00", origin=r["origin"],
        owner_validated=True, diagnostic_reason="ORIGIN_OWNER_VALIDATED")
    h = flow_pl_store.feature_origin_provenance_health("2026-09-30")
    assert h["origin_direction_evolved"] == 1
    assert h["origin_uncertain_to_bearish"] == 1
