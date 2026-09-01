from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from engine.evidence_pipeline import _connect
from engine.outcome_grader import horizon_integrity, run_grader
from engine.trigger_observatory import (
    effectiveness,
    initialize_store,
    observation_integrity_validation,
    observe_price,
    predictive_validation,
    record_trigger,
)

ROOT = Path(__file__).resolve().parents[1]


def _decision(conn, *, did: str, observed_at: str, session: str = "MARKET_OPEN",
              direction: str = "BEARISH", won: bool = True, snapshot: dict | None = None,
              status: str = "GRADED"):
    snap = {
        "action": "NO_TRADE",
        "actionable": False,
        "execution_actionable": False,
        "observational_learning_eligible": True,
        "apex_release_version": "69.9.5",
        **(snapshot or {}),
    }
    conn.execute(
        """INSERT INTO decisions(decision_id,observed_at,ticker,session,direction,action,
           entry_price,confidence,learning_eligible,snapshot_json,status)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (did, observed_at, "SPX", session, direction, "NO_TRADE", 6500.0, 65.0, 1, json.dumps(snap), status),
    )
    if status == "GRADED":
        conn.execute(
            """INSERT INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json)
               VALUES(?,?,?,?,?,?)""",
            (did, "2026-08-31T14:10:00+00:00", "GRADED", None, 300,
             json.dumps({"won": won, "direction_correct": won, "horizon_seconds": 300})),
        )


def _grade_trigger(trigger_db: Path, trigger_id: str, *, won: bool):
    with sqlite3.connect(trigger_db) as conn:
        conn.execute(
            """UPDATE observed_trade_triggers SET canonical_grade_status='GRADED',
               canonical_grade_label=?,canonical_grade_json=?,canonical_graded_at=?
               WHERE trigger_id=?""",
            ("WIN" if won else "LOSS", json.dumps({"won": won}), "2026-08-31T14:10:00+00:00", trigger_id),
        )


def test_late_first_observation_is_incomplete_not_five_minute_observed(tmp_path):
    trigger_db = tmp_path / "triggers.db"
    rec = record_trigger(
        source="CANONICAL_DECISION", trigger_type="NO_TRADE", direction="BEARISH",
        disposition="BLOCKED", triggered_at="2026-08-31T14:00:00+00:00",
        price=6500.0, entry=6500.0, blockers=["THESIS_INVALIDATED"],
        decision_id="late-first", source_event_key="late-first", path=str(trigger_db),
    )
    out = observe_price(
        symbol="SPX", price=6480.0, observed_at="2026-08-31T14:15:00+00:00", path=str(trigger_db)
    )
    assert out["late_samples"] == 1
    assert out["observation_window_incomplete"] == 1
    with sqlite3.connect(trigger_db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM observed_trade_triggers WHERE trigger_id=?", (rec["trigger_id"],)).fetchone()
        obs = conn.execute("SELECT * FROM trade_trigger_price_observations WHERE trigger_id=?", (rec["trigger_id"],)).fetchone()
    assert row["status"] == "OBSERVATION_WINDOW_INCOMPLETE"
    assert row["window_integrity_status"] == "LATE"
    assert row["in_window_observation_count"] == 0
    assert row["late_observation_count"] == 1
    assert row["mfe_points"] is None
    assert row["mae_points"] is None
    assert row["outcome_label"] == "OBSERVATION_WINDOW_INCOMPLETE"
    assert obs["window_class"] == "LATE"
    assert obs["elapsed_seconds"] == 900.0

    eff = effectiveness(path=str(trigger_db))
    g = eff["groups"][0]
    assert g["five_minute_observed"] == 0
    assert g["avg_mfe_points"] is None
    assert g["late"] == 1
    assert eff["observation_window_integrity"]["late"] == 1


def test_historical_reconciliation_recomputes_excursion_from_in_window_only(tmp_path):
    trigger_db = tmp_path / "triggers.db"
    rec = record_trigger(
        source="CANONICAL_DECISION", trigger_type="NO_TRADE", direction="BEARISH",
        disposition="BLOCKED", triggered_at="2026-08-31T14:00:00+00:00",
        price=6500.0, entry=6500.0, blockers=["THESIS_INVALIDATED"],
        decision_id="mixed-window", source_event_key="mixed-window", path=str(trigger_db),
    )
    with sqlite3.connect(trigger_db) as conn:
        conn.execute(
            """INSERT INTO trade_trigger_price_observations(
               observation_id,trigger_id,observed_at,price,favorable_points,adverse_points,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            ("in", rec["trigger_id"], "2026-08-31T14:01:00+00:00", 6498.0, 2.0, 0.0, "2026-08-31T14:01:00+00:00"),
        )
        conn.execute(
            """INSERT INTO trade_trigger_price_observations(
               observation_id,trigger_id,observed_at,price,favorable_points,adverse_points,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            ("late", rec["trigger_id"], "2026-08-31T14:15:00+00:00", 6470.0, 30.0, 0.0, "2026-08-31T14:15:00+00:00"),
        )
        # Simulate contaminated legacy aggregate.
        conn.execute(
            "UPDATE observed_trade_triggers SET mfe_points=30.0,mae_points=0.0,outcome_label='FAVORABLE',status='OBSERVED' WHERE trigger_id=?",
            (rec["trigger_id"],),
        )
    initialize_store(str(trigger_db))
    with sqlite3.connect(trigger_db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM observed_trade_triggers WHERE trigger_id=?", (rec["trigger_id"],)).fetchone()
        samples = conn.execute(
            "SELECT observed_at,elapsed_seconds,window_class FROM trade_trigger_price_observations WHERE trigger_id=? ORDER BY observed_at",
            (rec["trigger_id"],),
        ).fetchall()
    assert row["window_integrity_status"] == "IN_WINDOW"
    assert row["in_window_observation_count"] == 1
    assert row["late_observation_count"] == 1
    assert row["mfe_points"] == 2.0
    assert row["window_mfe_points"] == 2.0
    assert [x["window_class"] for x in samples] == ["IN_WINDOW", "LATE"]
    assert [x["elapsed_seconds"] for x in samples] == [60.0, 900.0]


def test_late_excursion_cannot_create_potential_blocker_regret(tmp_path):
    trigger_db = tmp_path / "triggers.db"
    evidence_db = tmp_path / "evidence.db"
    with _connect(evidence_db) as conn:
        _decision(conn, did="late-regret", observed_at="2026-08-31T14:00:00+00:00", won=True)
    rec = record_trigger(
        source="CANONICAL_DECISION", trigger_type="NO_TRADE", direction="BEARISH",
        disposition="BLOCKED", triggered_at="2026-08-31T14:00:00+00:00",
        price=6500.0, entry=6500.0, target1=6497.0, blockers=["THESIS_INVALIDATED"],
        decision_id="late-regret", source_event_key="late-regret", path=str(trigger_db),
    )
    _grade_trigger(trigger_db, rec["trigger_id"], won=True)
    observe_price(symbol="SPX", price=6490.0, observed_at="2026-08-31T14:15:00+00:00", path=str(trigger_db))
    out = predictive_validation(path=str(trigger_db), evidence_path=str(evidence_db))
    ar = out["abstention_regret"]
    assert ar["classification_counts"]["DIRECTIONALLY_CORRECT_BUT_NOT_PROVEN_TRADEABLE"] == 1
    assert ar["classification_counts"].get("POTENTIAL_BLOCKER_REGRET", 0) == 0
    assert ar["overall"]["movement_threshold_evaluable"] == 0
    assert ar["overall"]["observation_window_integrity"]["LATE"] == 1
    assert ar["observation_window_integrity"]["late_samples_regret_eligible"] is False


def test_explicit_canonical_target_can_recover_threshold_but_generic_level_cannot(tmp_path):
    trigger_db = tmp_path / "triggers.db"
    evidence_db = tmp_path / "evidence.db"
    explicit_snapshot = {
        "institutional_decision_object": {
            "targets_and_decision_levels": {"tp1": 6497.0, "support": 6480.0}
        }
    }
    generic_snapshot = {
        "institutional_decision_object": {
            "targets_and_decision_levels": {"support": 6497.0, "resistance": 6510.0}
        }
    }
    with _connect(evidence_db) as conn:
        _decision(conn, did="explicit", observed_at="2026-08-31T14:00:00+00:00", won=True, snapshot=explicit_snapshot)
        _decision(conn, did="generic", observed_at="2026-08-31T14:00:00+00:00", won=True, snapshot=generic_snapshot)
    explicit = record_trigger(
        source="CANONICAL_DECISION", trigger_type="NO_TRADE", direction="BEARISH",
        disposition="BLOCKED", triggered_at="2026-08-31T14:00:00+00:00", price=6500.0, entry=6500.0,
        blockers=["THESIS_INVALIDATED"], decision_id="explicit", source_event_key="explicit", path=str(trigger_db),
    )
    generic = record_trigger(
        source="CANONICAL_DECISION", trigger_type="NO_TRADE", direction="BEARISH",
        disposition="BLOCKED", triggered_at="2026-08-31T14:00:30+00:00", price=6500.0, entry=6500.0,
        blockers=["THESIS_INVALIDATED"], decision_id="generic", source_event_key="generic", path=str(trigger_db),
    )
    _grade_trigger(trigger_db, explicit["trigger_id"], won=True)
    _grade_trigger(trigger_db, generic["trigger_id"], won=True)
    observe_price(symbol="SPX", price=6496.0, observed_at="2026-08-31T14:01:00+00:00", path=str(trigger_db))
    out = predictive_validation(path=str(trigger_db), evidence_path=str(evidence_db))
    ar = out["abstention_regret"]
    assert ar["classification_counts"]["POTENTIAL_BLOCKER_REGRET"] == 1
    assert ar["classification_counts"]["DIRECTIONALLY_CORRECT_BUT_NOT_PROVEN_TRADEABLE"] == 1
    sources = ar["overall"]["movement_threshold_sources"]
    assert any(k.startswith("PERSISTED_CANONICAL_EXPLICIT_TARGET:") for k in sources)
    assert sources["UNAVAILABLE"] == 1
    assert ar["movement_threshold_contract"]["generic_support_resistance_levels_inferred"] is False


def test_market_open_later_bucket_is_narrowed(tmp_path):
    trigger_db = tmp_path / "triggers.db"
    evidence_db = tmp_path / "evidence.db"
    with _connect(evidence_db) as conn:
        _decision(conn, did="m75", observed_at="2026-08-31T14:45:00+00:00", won=False)
        _decision(conn, did="m105", observed_at="2026-08-31T15:15:00+00:00", won=False)
    for did, ts in (("m75", "2026-08-31T14:45:00+00:00"), ("m105", "2026-08-31T15:15:00+00:00")):
        rec = record_trigger(
            source="CANONICAL_DECISION", trigger_type="NO_TRADE", direction="BEARISH",
            disposition="BLOCKED", triggered_at=ts, price=6500.0, entry=6500.0,
            blockers=["THESIS_INVALIDATED"], decision_id=did, source_event_key=did, path=str(trigger_db),
        )
        _grade_trigger(trigger_db, rec["trigger_id"], won=False)
    out = predictive_validation(path=str(trigger_db), evidence_path=str(evidence_db))
    buckets = {x["market_open_elapsed_bucket"] for x in out["abstention_regret"]["market_open_elapsed"]}
    assert "MARKET_OPEN_60_90" in buckets
    assert "MARKET_OPEN_90_120" in buckets
    assert "LATER_MARKET_OPEN_60_PLUS" not in buckets


def test_canonical_grader_horizon_is_independently_verified(tmp_path):
    evidence_db = tmp_path / "evidence.db"
    with _connect(evidence_db) as conn:
        conn.execute(
            """INSERT INTO decisions(decision_id,observed_at,ticker,session,direction,action,
               entry_price,confidence,learning_eligible,snapshot_json,status)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            ("grade-1", "2026-08-31T13:30:00+00:00", "SPX", "MARKET_OPEN", "BEARISH", "NO_TRADE",
             6500.0, 65.0, 1, json.dumps({"observational_only": True}), "PENDING"),
        )
        conn.execute("INSERT INTO price_samples(ticker,observed_at,price) VALUES(?,?,?)", ("SPX", "2026-08-31T13:31:00+00:00", 6498.0))
        conn.execute("INSERT INTO price_samples(ticker,observed_at,price) VALUES(?,?,?)", ("SPX", "2026-08-31T13:35:00+00:00", 6495.0))
        conn.execute("INSERT INTO price_samples(ticker,observed_at,price) VALUES(?,?,?)", ("SPX", "2026-08-31T13:40:00+00:00", 6480.0))
    run_grader(evidence_db, horizon_seconds=300)
    integrity = horizon_integrity(evidence_db)
    assert integrity["configured_default_horizon_seconds"] == 300
    assert integrity["configured_is_expected"] is True
    assert integrity["stored_horizon_mismatch_count"] == 0
    assert integrity["forward_timestamp_out_of_window_count"] == 0
    assert integrity["status"] == "VERIFIED"
    with _connect(evidence_db) as conn:
        row = conn.execute("SELECT outcome_json FROM grading_results WHERE decision_id='grade-1'").fetchone()
    outcome = json.loads(row["outcome_json"])
    assert outcome["forward_observed_at"] == "2026-08-31T13:35:00+00:00"
    assert outcome["price_query_window_enforced"] is True
    assert outcome["horizon_seconds"] == 300


def test_observation_integrity_endpoint_contract(tmp_path):
    trigger_db = tmp_path / "triggers.db"
    evidence_db = tmp_path / "evidence.db"
    out = observation_integrity_validation(path=str(trigger_db), evidence_path=str(evidence_db))
    assert out["behavioral_authority"] is False
    assert out["execution_authority"] is False
    assert out["broker_mutation"] is False
    assert out["production_effect"] == "OBSERVATIONAL_ONLY"


def test_release_truth_and_guardrails_are_69_9_5():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"]
    assert tuple(map(int, manifest["apex_version"].split("."))) >= (69, 9, 5)
    g = manifest["guardrails"]
    assert g["five_minute_observation_integrity_enforced"] is True
    assert g["late_observations_excluded_from_five_minute_metrics"] is True
    assert g["late_first_observation_can_terminalize_as_five_minute_observed"] is False
    assert g["window_missed_marked_observation_window_incomplete"] is True
    assert g["regret_requires_valid_in_window_excursion"] is True
    assert g["canonical_grader_expected_horizon_seconds"] == 300
    assert g["generic_level_threshold_inference_enabled"] is False
    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert f"apex_version: {manifest['apex_version']}" in registry
    assert "/api/triggers/observation-integrity" in registry
    assert "five_minute_observation_integrity" in registry
    routes = (ROOT / "engine/trigger_observatory_routes.py").read_text()
    assert '@app.get("/api/triggers/observation-integrity")' in routes


def test_dashboard_surfaces_window_integrity_truth():
    html = (ROOT / "templates/premium_discipline_command_center.html").read_text()
    assert "Five-Minute Observation Integrity" in html
    assert "late-only" in html
    assert "OBSERVATION_WINDOW_INCOMPLETE" in html
    assert "late excluded from 5m metrics" in html
