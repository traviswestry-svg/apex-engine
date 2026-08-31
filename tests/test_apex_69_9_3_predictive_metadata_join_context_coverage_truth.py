from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from engine.dynamic_state_outcome_calibration import context_diversity_audit, ensure_schema
from engine.evidence_pipeline import _connect
from engine.trigger_observatory import predictive_validation, record_trigger

ROOT = Path(__file__).resolve().parents[1]


def _grade_trigger(trigger_db: Path, *, did: str, direction: str, confidence: float, won: bool):
    rec = record_trigger(
        source="CANONICAL_DECISION",
        trigger_type="NO_TRADE",
        direction=direction,
        disposition="BLOCKED",
        confidence=confidence,
        price=6500.0,
        blockers=["THESIS_INVALIDATED"],
        decision_id=did,
        source_event_key=did,
        path=str(trigger_db),
    )
    with sqlite3.connect(trigger_db) as conn:
        conn.execute(
            """UPDATE observed_trade_triggers
               SET canonical_grade_status='GRADED', canonical_grade_label=?,
                   outcome_label=?, mfe_points=?, mae_points=?
               WHERE trigger_id=?""",
            (
                "WIN" if won else "LOSS",
                "FAVORABLE" if won else "ADVERSE",
                3.0 if won else 0.5,
                0.5 if won else 3.0,
                rec["trigger_id"],
            ),
        )


def _decision(conn, *, did: str, session: str, snapshot_json: str, action: str = "NO_TRADE"):
    conn.execute(
        """INSERT INTO decisions(decision_id,observed_at,ticker,session,direction,action,
           entry_price,confidence,learning_eligible,snapshot_json,status)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            did,
            "2026-08-31T14:00:00+00:00",
            "SPX",
            session,
            "BEARISH",
            action,
            6500.0,
            65.0,
            1,
            snapshot_json,
            "GRADED",
        ),
    )
    conn.execute(
        """INSERT INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json)
           VALUES(?,?,?,?,?,?)""",
        (did, "2026-08-31T14:05:00+00:00", "GRADED", None, 300, json.dumps({"won": True})),
    )


def test_legacy_snapshot_without_release_version_does_not_break_metadata_join(tmp_path):
    trigger_db = tmp_path / "triggers.db"
    evidence_db = tmp_path / "evidence.db"
    with _connect(evidence_db) as conn:
        _decision(
            conn,
            did="legacy-1",
            session="MARKET_OPEN",
            snapshot_json=json.dumps(
                {
                    "action": "NO_TRADE",
                    "actionable": False,
                    "execution_actionable": False,
                    "observational_learning_eligible": True,
                }
            ),
        )
    _grade_trigger(trigger_db, did="legacy-1", direction="BEARISH", confidence=65.0, won=True)

    out = predictive_validation(path=str(trigger_db), evidence_path=str(evidence_db))
    join = out["metadata_join"]
    assert join["status"] == "COMPLETE"
    assert join["metadata_joined"] == 1
    assert join["metadata_join_rate_pct"] == 100.0
    assert join["session_known"] == 1
    assert join["grade_horizon_joined"] == 1
    assert join["parse_error_count"] == 0
    assert join["release_version_known"] == 0
    assert out["cross_cohorts"]["session_x_direction"][0]["session"] == "MARKET_OPEN"
    assert out["cross_cohorts"]["grade_horizon_x_direction"][0]["grade_horizon_seconds"] == "300"
    classes = {x["decision_class"]: x for x in out["decision_class_effectiveness"]}
    assert classes["OBSERVATIONAL_NO_TRADE"]["canonical_graded"] == 1


def test_one_bad_snapshot_cannot_clear_valid_metadata_joins(tmp_path):
    trigger_db = tmp_path / "triggers.db"
    evidence_db = tmp_path / "evidence.db"
    with _connect(evidence_db) as conn:
        _decision(
            conn,
            did="good",
            session="PREMARKET",
            snapshot_json=json.dumps(
                {
                    "action": "NO_TRADE",
                    "execution_actionable": False,
                    "observational_learning_eligible": True,
                }
            ),
        )
        _decision(conn, did="bad", session="MARKET_OPEN", snapshot_json="{not-json")
    _grade_trigger(trigger_db, did="good", direction="BEARISH", confidence=65.0, won=True)
    _grade_trigger(trigger_db, did="bad", direction="BEARISH", confidence=75.0, won=False)

    out = predictive_validation(path=str(trigger_db), evidence_path=str(evidence_db))
    join = out["metadata_join"]
    assert join["status"] == "PARTIAL"
    assert join["graded_links_with_decision_id"] == 2
    assert join["metadata_joined"] == 1
    assert join["metadata_missing"] == 1
    assert join["metadata_join_rate_pct"] == 50.0
    assert join["parse_error_count"] == 1
    assert join["single_row_parse_failure_cannot_clear_valid_joins"] is True
    assert any(x["session"] == "PREMARKET" for x in out["cross_cohorts"]["session_x_direction"])


def test_context_quality_reports_partial_recovery_not_full_health(tmp_path):
    db = tmp_path / "evidence.db"
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        conn.execute("CREATE TABLE grading_results(decision_id TEXT PRIMARY KEY,status TEXT NOT NULL)")
        for i in range(25):
            did = f"d{i}"
            residual_present = i < 8
            residual_value = bool(i % 2) if residual_present else None
            ctx = {
                "policy_state": "NORMAL" if residual_present else "UNKNOWN",
                "alert_state": "NORMAL" if residual_present else "UNKNOWN",
                "event_phase": "UNKNOWN",
                "gamma_term_divergence": None,
                "near_term_gamma_fragility": None,
                "residual_pressure_opposes": residual_value,
                "flow_independence_bucket": "UNKNOWN",
                "capture_provenance": {
                    "policy_state": {"status": "SOURCE_PRESENT" if residual_present else "SOURCE_MISSING"},
                    "alert_state": {"status": "SOURCE_PRESENT" if residual_present else "SOURCE_MISSING"},
                    "event_phase": {"status": "SOURCE_MISSING"},
                    "gamma_term_divergence": {"status": "SOURCE_MISSING"},
                    "near_term_gamma_fragility": {"status": "SOURCE_MISSING"},
                    "residual_pressure_opposes": {"status": "SOURCE_PRESENT" if residual_present else "SOURCE_MISSING"},
                    "flow_independence_bucket": {"status": "SOURCE_MISSING"},
                },
            }
            conn.execute(
                """INSERT INTO dynamic_state_decision_context(
                   decision_id,captured_at,schema_version,policy_version,policy_state,alert_state,event_phase,
                   gamma_term_divergence,near_term_gamma_fragility,residual_pressure_opposes,flow_independence_bucket,
                   threshold_adjustment_points,conviction_penalty_points,consensus_penalty_points,context_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    did,
                    "2026-08-31T14:00:00+00:00",
                    "test",
                    None,
                    ctx["policy_state"],
                    ctx["alert_state"],
                    "UNKNOWN",
                    0,
                    0,
                    int(bool(residual_value)),
                    "UNKNOWN",
                    0.0,
                    0.0,
                    0.0,
                    json.dumps(ctx),
                ),
            )
            conn.execute("INSERT INTO grading_results(decision_id,status) VALUES(?,?)", (did, "GRADED"))

    out = context_diversity_audit(db)
    assert out["variable_field_count"] == 1
    assert out["context_quality_deficient"] is False
    assert out["context_coverage_complete"] is False
    assert out["context_coverage_partial"] is True
    assert out["quality_state"] == "PARTIAL_CONTEXT_RECOVERY"
    assert out["partial_coverage_field_count"] >= 1
    assert out["missing_coverage_field_count"] >= 1
    assert out["fields"]["residual_pressure_opposes"]["source_present_pct"] == 32.0


def test_release_truth_and_guardrails_are_69_9_3():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"] == "69.9.3"
    assert manifest["build_name"] == "Predictive Metadata Join & Context Coverage Truth Closure"
    g = manifest["guardrails"]
    assert g["predictive_metadata_join_diagnostics_enabled"] is True
    assert g["predictive_metadata_single_row_parse_isolation"] is True
    assert g["predictive_metadata_join_failure_cannot_clear_valid_rows"] is True
    assert g["context_quality_partial_recovery_explicit"] is True
    assert g["context_quality_does_not_equate_partial_coverage_with_complete"] is True
    assert g["metadata_join_changes_trade_decisions"] is False
    assert g["metadata_join_auto_activates_calibration"] is False
    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert "apex_version: 69.9.3" in registry
    assert "predictive_metadata_join_diagnostics" in registry
    assert "context_coverage_truth_state" in registry


def test_dashboard_surfaces_metadata_join_and_partial_context_truth():
    html = (ROOT / "templates/premium_discipline_command_center.html").read_text()
    assert "metadata join:" in html
    assert "metadata_join_rate_pct" in html
    assert "grade_horizon_joined" in html
    assert "context_coverage_partial" in html
    assert "fields complete" in html
