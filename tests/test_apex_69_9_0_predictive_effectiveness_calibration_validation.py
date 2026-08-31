from __future__ import annotations
import json
import sqlite3
from pathlib import Path

from engine.trigger_observatory import initialize_store, predictive_validation, record_trigger

ROOT = Path(__file__).resolve().parents[1]

def test_predictive_validation_is_observational_and_groups_confidence_blockers(tmp_path):
    trigger_db = tmp_path / "triggers.db"
    evidence_db = tmp_path / "evidence.db"
    a = record_trigger(source="CANONICAL_DECISION", trigger_type="NO_TRADE", direction="BULLISH",
                       disposition="BLOCKED", confidence=44.0, price=100.0,
                       blockers=["LOW_CONVICTION"], decision_id="d1", source_event_key="d1", path=str(trigger_db))
    b = record_trigger(source="CANONICAL_DECISION", trigger_type="NO_TRADE", direction="BEARISH",
                       disposition="BLOCKED", confidence=74.0, price=100.0,
                       blockers=["EVENT_RISK"], decision_id="d2", source_event_key="d2", path=str(trigger_db))
    with sqlite3.connect(trigger_db) as c:
        c.execute("UPDATE observed_trade_triggers SET canonical_grade_status='GRADED',canonical_grade_label='WIN',outcome_label='FAVORABLE',mfe_points=3,mae_points=1 WHERE trigger_id=?", (a["trigger_id"],))
        c.execute("UPDATE observed_trade_triggers SET canonical_grade_status='GRADED',canonical_grade_label='LOSS',outcome_label='ADVERSE',mfe_points=1,mae_points=4 WHERE trigger_id=?", (b["trigger_id"],))
    out = predictive_validation(path=str(trigger_db), evidence_path=str(evidence_db))
    assert out["ok"] is True
    assert out["production_effect"] == "OBSERVATIONAL_ONLY"
    assert out["behavioral_authority"] is False
    assert out["execution_authority"] is False
    assert out["broker_mutation"] is False
    assert out["automatic_calibration_activation"] is False
    assert out["canonical_graded_links"] == 2
    bands = {x["band"]: x for x in out["confidence_bands"]}
    assert bands["40-49.9"]["canonical_win_rate_pct"] == 100.0
    assert bands["70-79.9"]["canonical_win_rate_pct"] == 0.0
    blockers = {x["blocker"]: x for x in out["blocker_effectiveness"]}
    assert blockers["LOW_CONVICTION"]["canonical_graded"] == 1
    assert blockers["EVENT_RISK"]["canonical_graded"] == 1

def test_release_truth_and_guardrails_are_69_9_0():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"]
    assert tuple(map(int, manifest["apex_version"].split("."))) >= (69, 9, 0)
    g = manifest["guardrails"]
    assert g["predictive_validation_observational_only"] is True
    assert g["predictive_validation_changes_trade_decisions"] is False
    assert g["predictive_validation_changes_execution_authority"] is False
    assert g["predictive_validation_auto_activates_calibration"] is False
    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert f"apex_version: {manifest['apex_version']}" in registry
    assert "/api/triggers/predictive-validation" in registry

def test_dashboard_surfaces_validation_without_activation_controls():
    html = (ROOT / "templates/premium_discipline_command_center.html").read_text()
    assert "Decision Quality & Calibration Validation" in html
    assert "/api/triggers/predictive-validation?symbol=SPX" in html
    assert "Associational validation only" in html
