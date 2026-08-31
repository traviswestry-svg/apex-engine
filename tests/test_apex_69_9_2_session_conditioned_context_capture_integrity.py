from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

from engine.dynamic_state_outcome_calibration import calibration_summary, context_backfill, extract_context
from engine.dynamic_state_calibration_governance import compare_buckets
from engine.evidence_pipeline import _connect
from engine.historical_evidence_lifecycle import build_snapshot
from engine.trigger_observatory import predictive_validation, record_trigger

ROOT = Path(__file__).resolve().parents[1]


def test_missing_boolean_context_is_unknown_not_false():
    ctx = extract_context({})
    assert ctx["event_phase"] == "UNKNOWN"
    assert ctx["gamma_term_divergence"] is None
    assert ctx["near_term_gamma_fragility"] is None
    assert ctx["residual_pressure_opposes"] is None
    assert ctx["capture_provenance"]["gamma_term_divergence"]["status"] == "SOURCE_MISSING"
    assert ctx["capture_provenance"]["event_phase"]["status"] == "SOURCE_MISSING"


def test_nested_canonical_policy_and_dynamic_state_are_source_verified():
    snap = {
        "institutional_decision_object": {
            "conviction": {
                "dynamic_state_policy": {
                    "version": "68.5.3", "state": "NORMAL", "modifiers": [],
                    "threshold_adjustment_points": 0.0,
                    "conviction_penalty_points": 0.0,
                    "consensus_penalty_points": 0.0,
                }
            }
        },
        "dynamic_state": {
            "event_phase": {"phase": "PRE_EVENT"},
            "gamma_term_structure": {"term_divergence": True, "near_term_fragility": False},
            "flow_excitation": {"independent_evidence_factor": 0.82},
            "residual_pressure": {"unresolved": False},
        },
    }
    ctx = extract_context(snap)
    assert ctx["policy_state"] == "NORMAL"
    assert ctx["alert_state"] == "NORMAL"
    assert ctx["event_phase"] == "PRE_EVENT"
    assert ctx["gamma_term_divergence"] is True
    assert ctx["near_term_gamma_fragility"] is False
    assert ctx["flow_independence_bucket"] == "INDEPENDENT"
    assert ctx["residual_pressure_opposes"] is False
    for field in (
        "policy_state", "alert_state", "event_phase", "gamma_term_divergence",
        "near_term_gamma_fragility", "flow_independence_bucket",
        "residual_pressure_opposes",
    ):
        assert ctx["capture_provenance"][field]["status"] == "SOURCE_PRESENT"


def test_historical_snapshot_reconstructs_dynamic_context_after_decision():
    result = {
        "institutional_decision_object": {
            "ticker": "SPX", "timestamp": "2026-08-31T14:00:00+00:00",
            "action": "NO_TRADE", "direction": "BEARISH", "actionable": False,
            "conviction": {
                "raw_conviction": 68.0,
                "dynamic_state_policy": {"state": "NORMAL", "modifiers": [], "version": "68.5.3"},
            },
            "institutional_thesis": {"dominant_direction": "BEARISH"},
        },
        "market_state": {"price": 6500.0},
    }
    reconstructed = {
        "available": True,
        "flow_excitation": {"available": True, "independent_evidence_factor": 0.75},
        "residual_pressure": {"available": True, "unresolved": False},
        "gamma_path": {"available": True, "current_regime": "NEGATIVE"},
        "gamma_term_structure": {"available": True, "term_divergence": True, "near_term_fragility": False},
        "event_phase": {"available": True, "phase": "NORMAL"},
    }
    with patch("engine.dynamic_state.build_dynamic_state", return_value=reconstructed):
        snap = build_snapshot(result, session_state="MARKET_OPEN")
    assert snap["dynamic_state"] == reconstructed
    assert snap["dynamic_state_policy"]["state"] == "NORMAL"
    assert snap["flow_excitation"]["independent_evidence_factor"] == 0.75
    assert snap["gamma_term_structure"]["term_divergence"] is True
    assert snap["apex_release_version"] == "69.9.2"


def test_context_backfill_only_applies_source_present_snapshot_values(tmp_path):
    db = tmp_path / "evidence.db"
    source_snapshot = {
        "dynamic_state_policy": {"state": "NORMAL", "modifiers": [], "version": "68.5.3"},
        "dynamic_state": {
            "event_phase": {"phase": "PRE_EVENT"},
            "gamma_term_structure": {"term_divergence": True, "near_term_fragility": False},
            "flow_excitation": {"independent_evidence_factor": 0.9},
        },
    }
    with _connect(db) as conn:
        from engine.dynamic_state_outcome_calibration import ensure_schema
        ensure_schema(conn)
        for did, snap in (("recoverable", source_snapshot), ("missing", {})):
            conn.execute(
                """INSERT INTO decisions(decision_id,observed_at,ticker,session,direction,action,
                   entry_price,confidence,learning_eligible,snapshot_json,status)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (did, "2026-08-31T14:00:00+00:00", "SPX", "MARKET_OPEN", "BEARISH",
                 "NO_TRADE", 6500.0, 65.0, 1, json.dumps(snap), "GRADED"),
            )
            conn.execute(
                """INSERT INTO dynamic_state_decision_context(
                   decision_id,captured_at,schema_version,policy_version,policy_state,alert_state,event_phase,
                   gamma_term_divergence,near_term_gamma_fragility,residual_pressure_opposes,flow_independence_bucket,
                   threshold_adjustment_points,conviction_penalty_points,consensus_penalty_points,context_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (did, "2026-08-31T14:00:00+00:00", "legacy", None, "UNKNOWN", "UNKNOWN",
                 "UNKNOWN", 0, 0, 0, "UNKNOWN", 0.0, 0.0, 0.0, "{}"),
            )
    preview = context_backfill(db, apply=False)
    assert preview["status"] == "PREVIEW"
    assert preview["recoverable_decisions"] == 1
    assert preview["recoverable_fields"] >= 5
    assert preview["applied_updates"] == 0
    applied = context_backfill(db, apply=True)
    assert applied["status"] == "APPLIED"
    assert applied["applied_updates"] == 1
    assert applied["missing_sources_never_inferred"] is True
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        recovered = conn.execute(
            "SELECT * FROM dynamic_state_decision_context WHERE decision_id='recoverable'"
        ).fetchone()
        missing = conn.execute(
            "SELECT * FROM dynamic_state_decision_context WHERE decision_id='missing'"
        ).fetchone()
    assert recovered["event_phase"] == "PRE_EVENT"
    assert recovered["gamma_term_divergence"] == 1
    assert recovered["flow_independence_bucket"] == "INDEPENDENT"
    assert missing["event_phase"] == "UNKNOWN"
    assert missing["policy_state"] == "UNKNOWN"


def _graded_trigger(trigger_db: Path, *, did: str, direction: str, confidence: float, won: bool):
    rec = record_trigger(
        source="CANONICAL_DECISION", trigger_type="NO_TRADE", direction=direction,
        disposition="BLOCKED", confidence=confidence, price=6500.0,
        blockers=["THESIS_INVALIDATED"], decision_id=did, source_event_key=did,
        path=str(trigger_db),
    )
    with sqlite3.connect(trigger_db) as conn:
        conn.execute(
            """UPDATE observed_trade_triggers SET canonical_grade_status='GRADED',
               canonical_grade_label=?,outcome_label=?,mfe_points=?,mae_points=?
               WHERE trigger_id=?""",
            ("WIN" if won else "LOSS", "FAVORABLE" if won else "ADVERSE",
             3.0 if won else 0.5, 0.5 if won else 3.0, rec["trigger_id"]),
        )


def test_predictive_validation_separates_session_decision_class_and_release(tmp_path):
    trigger_db = tmp_path / "triggers.db"
    evidence_db = tmp_path / "evidence.db"
    cases = [
        ("open_actionable", "BEARISH", 65.0, True, "MARKET_OPEN", True, False, "69.9.2"),
        ("pre_no_trade", "BEARISH", 75.0, False, "PREMARKET", False, True, "69.9.1"),
        ("open_no_trade", "BULLISH", 45.0, True, "MARKET_OPEN", False, True, "69.9.2"),
        ("pre_actionable", "BULLISH", 55.0, False, "PREMARKET", True, False, "69.9.2"),
    ]
    with _connect(evidence_db) as conn:
        for did, direction, confidence, won, session, actionable, observational, release in cases:
            snap = {
                "action": "ENTER" if actionable else "NO_TRADE",
                "actionable": actionable,
                "execution_actionable": actionable,
                "observational_learning_eligible": observational,
                "apex_release_version": release,
            }
            conn.execute(
                """INSERT INTO decisions(decision_id,observed_at,ticker,session,direction,action,
                   entry_price,confidence,learning_eligible,snapshot_json,status)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (did, "2026-08-31T14:00:00+00:00", "SPX", session, direction,
                 snap["action"], 6500.0, confidence, 1, json.dumps(snap), "GRADED"),
            )
            conn.execute(
                """INSERT INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json)
                   VALUES(?,?,?,?,?,?)""",
                (did, "2026-08-31T14:05:00+00:00", "GRADED", None, 300,
                 json.dumps({"won": won, "direction_correct": won})),
            )
            _graded_trigger(trigger_db, did=did, direction=direction, confidence=confidence, won=won)
    out = predictive_validation(path=str(trigger_db), evidence_path=str(evidence_db))
    three_way = out["cross_cohorts"]["direction_x_confidence_x_session"]
    assert any(x["session"] == "MARKET_OPEN" and x["direction"] == "BEARISH"
               and x["confidence_band"] == "60-69.9" for x in three_way)
    blocker_session = out["cross_cohorts"]["blocker_x_session"]
    assert any(x["blocker"] == "THESIS_INVALIDATED" and x["session"] == "PREMARKET"
               for x in blocker_session)
    classes = {x["decision_class"]: x for x in out["decision_class_effectiveness"]}
    assert classes["ACTIONABLE_TRADE"]["canonical_graded"] == 2
    assert classes["OBSERVATIONAL_NO_TRADE"]["canonical_graded"] == 2
    releases = {x["release_version"]: x for x in out["release_cohorts"]}
    assert releases["69.9.2"]["canonical_graded"] == 3
    assert releases["69.9.1"]["canonical_graded"] == 1
    assert out["confidence_reliability"]["session_conditioning_enabled"] is True



def test_missing_legacy_context_cannot_become_calibration_ready_false_bucket(tmp_path):
    db = tmp_path / "evidence.db"
    with _connect(db) as conn:
        from engine.dynamic_state_outcome_calibration import ensure_schema
        ensure_schema(conn)
        for i in range(25):
            did = f"legacy{i}"
            conn.execute(
                """INSERT INTO decisions(decision_id,observed_at,ticker,session,direction,action,
                   entry_price,confidence,learning_eligible,snapshot_json,status)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (did, "2026-08-31T14:00:00+00:00", "SPX", "MARKET_OPEN", "BEARISH",
                 "NO_TRADE", 6500.0, 65.0, 1, "{}", "GRADED"),
            )
            conn.execute(
                """INSERT INTO dynamic_state_decision_context(
                   decision_id,captured_at,schema_version,policy_version,policy_state,alert_state,event_phase,
                   gamma_term_divergence,near_term_gamma_fragility,residual_pressure_opposes,flow_independence_bucket,
                   threshold_adjustment_points,conviction_penalty_points,consensus_penalty_points,context_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (did, "2026-08-31T14:00:00+00:00", "legacy", None, "UNKNOWN", "UNKNOWN",
                 "NORMAL", 0, 0, 0, "UNKNOWN", 0.0, 0.0, 0.0,
                 json.dumps({"event_phase": "NORMAL", "gamma_term_divergence": False})),
            )
            conn.execute(
                """INSERT INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json)
                   VALUES(?,?,?,?,?,?)""",
                (did, "2026-08-31T14:05:00+00:00", "GRADED", None, 300,
                 json.dumps({"won": i % 2 == 0})),
            )
    summary = calibration_summary(db)
    assert summary["status"] == "CONTEXT_QUALITY_DEFICIENT"
    assert summary["source_verified_ready_bucket_count"] == 0
    gamma = {x["bucket"]: x for x in summary["dimensions"]["gamma_term_divergence"]}
    assert gamma["UNKNOWN"]["sample_size"] == 25
    assert gamma["UNKNOWN"]["calibration_ready"] is False
    comparison = compare_buckets(db, "gamma_term_divergence", "0", "1")
    assert comparison["challenger"]["raw_sample_size"] == 0
    assert comparison["incumbent"]["raw_sample_size"] == 0
    assert comparison["eligible_for_review"] is False


def test_release_truth_and_guardrails_are_69_9_2():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"] == "69.9.2"
    assert manifest["build_name"] == "Session-Conditioned Reliability & Calibration Context Capture Integrity Closure"
    g = manifest["guardrails"]
    assert g["session_conditioned_confidence_reliability_observational_only"] is True
    assert g["decision_class_effectiveness_separated"] is True
    assert g["calibration_context_missing_boolean_not_normalized_false"] is True
    assert g["calibration_context_backfill_requires_source_present"] is True
    assert g["calibration_context_backfill_missing_sources_inferred"] is False
    assert g["session_conditioned_reliability_changes_trade_decisions"] is False
    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert "apex_version: 69.9.2" in registry
    assert "/api/triggers/context-backfill" in registry
    assert "session_conditioned_reliability" in registry
    routes = (ROOT / "engine/trigger_observatory_routes.py").read_text()
    assert '@app.post("/api/triggers/context-backfill")' in routes
    assert '"/api/triggers/context-backfill"' in routes


def test_dashboard_surfaces_session_conditioning_and_backfill_integrity():
    html = (ROOT / "templates/premium_discipline_command_center.html").read_text()
    assert "Session × Direction × Confidence" in html
    assert "Decision Class" in html
    assert "Calibration Context Capture Integrity" in html
    assert "Missing source values are never inferred" in html
    assert "direction_x_confidence_x_session" in html
