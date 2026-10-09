import json
from pathlib import Path

from engine import flow_pl_store

ROOT = Path(__file__).resolve().parents[1]


def _use_db(tmp_path):
    flow_pl_store._DB_PATH = str(tmp_path / "tracking.db")
    flow_pl_store._DB_READY = False
    assert flow_pl_store.init_db()


def test_release_truth_and_guardrails():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == "69.10.37"
    assert manifest["build_name"] == "Forecast Diagnostics Production Promotion & Persistence Closure"
    g = manifest["guardrails"]
    assert g["origin_event_facts_persisted_at_canonical_binding"] is True
    assert g["excursion_owner_must_equal_registered_feature_sample"] is True
    assert g["settlement_fuzzy_matching_allowed"] is False
    assert g["settlement_nearest_time_matching_allowed"] is False
    assert g["settlement_cross_sample_excursion_borrowing_allowed"] is False
    assert g["settlement_synthetic_mfe_pl_allowed"] is False
    assert g["settlement_historical_identity_backfill_allowed"] is False


def test_origin_facts_survive_without_initial_mark_and_drive_exact_reobservation_candidate(tmp_path):
    _use_db(tmp_path)
    sid = "s_forward_691036"
    facts = [{
        "event_id": "evt-1", "ticker": "SPX", "contract_type": "CALL",
        "strike": 6750.0, "expiration": "2026-10-06", "position_side": "LONG",
        "contracts": 2, "multiplier": 100.0, "entry_time_et": "10:01:02",
        "entry_mark": 3.25,
    }]
    assert flow_pl_store.register_sample_identity(
        sample_id=sid, session_date="2026-10-06",
        legacy_cluster_key="SPX|CALL|2026-10-06|BULLISH",
        decision_time="2026-10-06T10:01:02", origin_event_ids=["evt-1"],
        origin_event_facts=facts)

    # No flow_pl_tracking row exists: this models a feature that sealed before an
    # initial mark was available. 69.10.36 must still preserve exact repricing facts.
    with flow_pl_store._conn() as c:
        assert c.execute("SELECT COUNT(*) n FROM flow_pl_tracking").fetchone()["n"] == 0

    rows = flow_pl_store.get_bound_origin_repricing_candidates("2026-10-06")
    assert len(rows) == 1
    assert rows[0]["sample_id"] == sid
    assert rows[0]["event_id"] == "evt-1"
    assert rows[0]["facts_source"] == "CANONICAL_ORIGIN_FACTS"
    assert rows[0]["entry_mark"] == 3.25

    h = flow_pl_store.feature_lifecycle_excursion_convergence_health("2026-10-06")
    assert h["registered_samples"] == 1
    assert h["samples_with_origin_bindings"] == 1
    assert h["samples_with_durable_origin_facts"] == 1
    assert h["samples_with_exact_excursion"] == 0
    assert h["bound_without_durable_facts"] == 0
    assert h["fuzzy_matching"] is False
    assert h["reconstructs_identity"] is False


def test_exact_registered_owner_is_still_required_for_excursion(tmp_path):
    _use_db(tmp_path)
    sid = "s_exact_owner"
    assert flow_pl_store.register_sample_identity(
        sample_id=sid, session_date="2026-10-06",
        legacy_cluster_key="SPX|PUT|2026-10-06|BEARISH",
        decision_time="2026-10-06T10:15:00", origin_event_ids=["evt-2"],
        origin_event_facts=[{"event_id":"evt-2","ticker":"SPX","contract_type":"PUT",
                            "strike":6700,"expiration":"2026-10-06","position_side":"LONG",
                            "contracts":1,"multiplier":100,"entry_time_et":"10:15:00","entry_mark":2.0}])
    assert flow_pl_store.record_sample_excursion(
        sample_id=sid, session_date="2026-10-06", ticker="SPX", pl_dollars=50.0,
        cost_basis=200.0, decision_time="2026-10-06T10:15:00",
        legacy_cluster_key="SPX|PUT|2026-10-06|BEARISH", require_registered_owner=True)
    assert flow_pl_store.record_sample_excursion(
        sample_id="s_wrong", session_date="2026-10-06", ticker="SPX", pl_dollars=50.0,
        cost_basis=200.0, decision_time="2026-10-06T10:15:00",
        legacy_cluster_key="SPX|PUT|2026-10-06|BEARISH", require_registered_owner=True) is None
    h = flow_pl_store.feature_lifecycle_excursion_convergence_health("2026-10-06")
    assert h["samples_with_exact_excursion"] == 1
    assert h["converged_samples"] == 1
    assert h["convergence_pct"] == 100.0
