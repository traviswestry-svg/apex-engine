from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from engine.dynamic_state_outcome_calibration import context_diversity_audit, ensure_schema
from engine.trigger_observatory import predictive_validation, record_trigger

ROOT = Path(__file__).resolve().parents[1]


def _graded_trigger(trigger_db: Path, *, key: str, direction: str, confidence: float, won: bool):
    rec = record_trigger(
        source="CANONICAL_DECISION",
        trigger_type="NO_TRADE",
        direction=direction,
        disposition="BLOCKED",
        confidence=confidence,
        price=100.0,
        blockers=["LOW_CONVICTION"],
        decision_id=key,
        source_event_key=key,
        path=str(trigger_db),
    )
    with sqlite3.connect(trigger_db) as c:
        c.execute(
            """UPDATE observed_trade_triggers
               SET canonical_grade_status='GRADED',
                   canonical_grade_label=?,
                   outcome_label=?,
                   mfe_points=?,
                   mae_points=?
               WHERE trigger_id=?""",
            ("WIN" if won else "LOSS", "FAVORABLE" if won else "ADVERSE",
             3.0 if won else 0.5, 0.5 if won else 3.0, rec["trigger_id"]),
        )
    return rec


def test_context_diversity_flags_large_but_collapsed_context(tmp_path):
    db = tmp_path / "evidence.db"
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        conn.execute("CREATE TABLE grading_results(decision_id TEXT PRIMARY KEY,status TEXT NOT NULL)")
        for i in range(25):
            did = f"d{i}"
            ctx = {
                "policy_state": "UNKNOWN",
                "alert_state": "UNKNOWN",
                "event_phase": "NORMAL",
                "gamma_term_divergence": False,
                "near_term_gamma_fragility": False,
                "residual_pressure_opposes": False,
                "flow_independence_bucket": "UNKNOWN",
            }
            conn.execute(
                """INSERT INTO dynamic_state_decision_context(
                   decision_id,captured_at,schema_version,policy_version,policy_state,alert_state,event_phase,
                   gamma_term_divergence,near_term_gamma_fragility,residual_pressure_opposes,flow_independence_bucket,
                   threshold_adjustment_points,conviction_penalty_points,consensus_penalty_points,context_json
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (did, "2026-08-31T14:00:00+00:00", "test", None, "UNKNOWN", "UNKNOWN", "NORMAL",
                 0, 0, 0, "UNKNOWN", 0.0, 0.0, 0.0, json.dumps(ctx)),
            )
            conn.execute("INSERT INTO grading_results(decision_id,status) VALUES(?,?)", (did, "GRADED"))
    out = context_diversity_audit(db)
    assert out["ok"] is True
    assert out["graded_contexts"] == 25
    assert out["context_quality_deficient"] is True
    assert out["quality_state"] == "CONTEXT_QUALITY_DEFICIENT"
    assert out["fields"]["event_phase"]["state"] == "CONSTANT"
    assert out["fields"]["alert_state"]["state"] == "UNKNOWN"
    assert out["fields"]["flow_independence_bucket"]["state"] == "UNKNOWN"
    assert out["fields"]["gamma_term_divergence"]["state"] == "CONSTANT"
    assert out["fields"]["event_phase"]["provenance"]


def test_context_diversity_recognizes_variable_field(tmp_path):
    db = tmp_path / "evidence.db"
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        conn.execute("CREATE TABLE grading_results(decision_id TEXT PRIMARY KEY,status TEXT NOT NULL)")
        for i in range(25):
            did = f"d{i}"
            event = "NORMAL" if i < 13 else "PRE_EVENT"
            conn.execute(
                """INSERT INTO dynamic_state_decision_context(
                   decision_id,captured_at,schema_version,policy_version,policy_state,alert_state,event_phase,
                   gamma_term_divergence,near_term_gamma_fragility,residual_pressure_opposes,flow_independence_bucket,
                   threshold_adjustment_points,conviction_penalty_points,consensus_penalty_points,context_json
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (did, "2026-08-31T14:00:00+00:00", "test", None, "NORMAL", "READY", event,
                 0, 0, 0, "INDEPENDENT", 0.0, 0.0, 0.0, "{}"),
            )
            conn.execute("INSERT INTO grading_results(decision_id,status) VALUES(?,?)", (did, "GRADED"))
    out = context_diversity_audit(db)
    assert out["context_quality_deficient"] is False
    assert out["fields"]["event_phase"]["state"] == "VARIABLE"
    assert out["variable_field_count"] >= 1


def test_confidence_reliability_detects_non_monotonic_outcomes(tmp_path):
    trigger_db = tmp_path / "triggers.db"
    evidence_db = tmp_path / "missing-evidence.db"
    for i in range(20):
        _graded_trigger(trigger_db, key=f"mid{i}", direction="BULLISH", confidence=65.0, won=True)
    for i in range(20):
        _graded_trigger(trigger_db, key=f"high{i}", direction="BEARISH", confidence=75.0, won=False)
    out = predictive_validation(path=str(trigger_db), evidence_path=str(evidence_db))
    rel = out["confidence_reliability"]
    assert rel["score_contract"] == "ORDINAL_DECISION_SCORE_NOT_EMPIRICAL_PROBABILITY"
    assert rel["probability_calibration_metrics_supported"] is False
    assert rel["state"] == "NON_MONOTONIC_OBSERVED_OUTCOMES"
    assert rel["comparable_band_count"] == 2
    assert rel["monotonicity_violations"]
    v = rel["monotonicity_violations"][0]
    assert v["lower_confidence_band"] == "60-69.9"
    assert v["higher_confidence_band"] == "70-79.9"
    bands = {x["band"]: x for x in out["confidence_bands"]}
    assert bands["60-69.9"]["canonical_win_rate_confidence_interval_95"]["lower_pct"] is not None
    cross = out["cross_cohorts"]["direction_x_confidence"]
    assert any(x["direction"] == "BULLISH" and x["confidence_band"] == "60-69.9" for x in cross)
    assert any(x["direction"] == "BEARISH" and x["confidence_band"] == "70-79.9" for x in cross)


def test_release_truth_and_guardrails_are_69_9_1():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"] == "69.9.1"
    assert manifest["build_name"] == "Calibration Context Diversity & Confidence Reliability Audit"
    g = manifest["guardrails"]
    assert g["calibration_context_diversity_audit_observational_only"] is True
    assert g["confidence_reliability_uses_ordinal_score_contract"] is True
    assert g["confidence_probability_metrics_disabled_without_probability_contract"] is True
    assert g["confidence_reliability_changes_trade_decisions"] is False
    assert g["confidence_reliability_auto_activates_calibration"] is False
    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert "apex_version: 69.9.1" in registry
    assert "calibration_context_diversity_audit" in registry
    assert "confidence_reliability_audit" in registry


def test_dashboard_surfaces_context_quality_and_confidence_reliability():
    html = (ROOT / "templates/premium_discipline_command_center.html").read_text()
    assert "Calibration Context Quality" in html
    assert "Confidence contract:" in html
    assert "Probability calibration metrics intentionally disabled" in html
    assert "direction_x_confidence" in html
