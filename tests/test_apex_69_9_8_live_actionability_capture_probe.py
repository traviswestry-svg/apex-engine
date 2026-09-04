from __future__ import annotations

import json
from pathlib import Path

from engine.historical_evidence_lifecycle import (
    actionability_capture_audit,
    capture_decision,
    runtime_status,
)
from engine.trigger_observatory import (
    actionability_capture_readiness_validation,
    initialize_store,
    predictive_validation,
)

ROOT = Path(__file__).resolve().parents[1]


def _scanner_result(ts: str = "2026-09-03T14:00:00+00:00") -> dict:
    return {
        "session": "MARKET_OPEN",
        "recommendation": "ENTER PUT NOW",
        "institutional_decision_object": {
            "ticker": "SPX",
            "timestamp": ts,
            "action": "NO_TRADE",
            "direction": "BEARISH",
            "actionable": False,
            "status": "THESIS_INVALIDATED",
            "market_state": {"price": 6500.0},
            "market_narrative": {"trade_guidance_enabled": True},
            "institutional_thesis": {
                "state": "INVALIDATED",
                "dominant_direction": "BEARISH",
            },
            "conviction": {"score": 65.0, "blocking_conditions": []},
            "targets_and_decision_levels": {"tp1": 6497.0},
        },
    }


def test_pregrade_audit_proves_current_release_capture_before_grading(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_NO_NEW_AFTER_ET", "11:30")
    monkeypatch.setenv("APEX_69_MARKET_MEMORY_CAPTURE_ENABLED", "false")
    evidence_db = tmp_path / "evidence.db"

    out = capture_decision(_scanner_result(), session_state="MARKET_OPEN", path=evidence_db)
    assert out["ok"] is True
    assert out["inserted"] is True

    audit = actionability_capture_audit(path=evidence_db)
    assert audit["status"] == "CURRENT_RELEASE_ENTRY_WINDOW_READY"
    assert audit["current_release_capture_hook_seen"] is True
    assert audit["current_release_rows"] == 1
    assert audit["current_release_entry_window_ready"] == 1
    assert audit["current_release_entry_window_ready_pct"] == 100.0
    row = audit["current_release_recent_decisions"][0]
    assert row["grade_present"] is False
    assert row["entry_window_source"] == "TRADE_RISK_GUARD_POLICY"
    assert row["entry_cutoff_et"] == "11:30"
    assert row["cutoff_passed"] is False
    assert row["lifecycle_stage"] == "DECISION_PERSISTED_ENTRY_WINDOW_READY"


def test_runtime_probe_records_capture_source_immediately(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_NO_NEW_AFTER_ET", "11:30")
    monkeypatch.setenv("APEX_69_MARKET_MEMORY_CAPTURE_ENABLED", "false")
    evidence_db = tmp_path / "evidence.db"
    capture_decision(_scanner_result(), session_state="MARKET_OPEN", path=evidence_db)

    status = runtime_status(path=evidence_db)
    runtime = status["runtime"]
    assert runtime["actionability_capture_attempts"] >= 1
    assert runtime["actionability_capture_ready"] >= 1
    assert runtime["last_actionability_capture_version"] == "69.10.0"
    assert runtime["last_entry_window_source"] == "TRADE_RISK_GUARD_POLICY"
    assert runtime["last_entry_cutoff_et"] == "11:30"
    assert runtime["last_cutoff_passed"] is False
    assert status["live_actionability_capture_audit"]["current_release_rows"] == 1


def test_readiness_endpoint_is_pregrade_and_does_not_require_trigger_linkage(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_NO_NEW_AFTER_ET", "11:30")
    monkeypatch.setenv("APEX_69_MARKET_MEMORY_CAPTURE_ENABLED", "false")
    evidence_db = tmp_path / "evidence.db"
    capture_decision(_scanner_result(), session_state="MARKET_OPEN", path=evidence_db)

    out = actionability_capture_readiness_validation(evidence_path=str(evidence_db))
    assert out["status"] == "CURRENT_RELEASE_ENTRY_WINDOW_READY"
    assert out["current_release_rows"] == 1
    assert out["current_release_entry_window_ready"] == 1
    assert out["execution_authority"] is False
    assert out["broker_mutation"] is False


def test_counterfactual_readiness_separates_pregrade_capture_from_graded_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_NO_NEW_AFTER_ET", "11:30")
    monkeypatch.setenv("APEX_69_MARKET_MEMORY_CAPTURE_ENABLED", "false")
    evidence_db = tmp_path / "evidence.db"
    trigger_db = tmp_path / "triggers.db"
    capture_decision(_scanner_result(), session_state="MARKET_OPEN", path=evidence_db)
    initialize_store(str(trigger_db))

    full = predictive_validation(path=str(trigger_db), evidence_path=str(evidence_db))
    readiness = full["counterfactual_regret"]["actionability_capture_readiness"]
    assert readiness["current_release_rows"] == 0  # no graded abstention/trigger link yet
    assert readiness["current_release_pregrade_rows"] == 1
    assert readiness["current_release_pregrade_entry_window_ready"] == 1
    assert readiness["status"] == "CURRENT_RELEASE_CAPTURED_AWAITING_QUALIFICATION_LINKAGE"
    assert readiness["live_capture_audit"]["status"] == "CURRENT_RELEASE_ENTRY_WINDOW_READY"


def test_release_truth_routes_and_guardrails_are_69_9_8():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"] == "69.10.0"
    assert manifest["build_name"] == "Flow Surprise Intelligence & Gamma Transition Dynamics"
    g = manifest["guardrails"]
    assert g["pregrade_live_actionability_audit_observational_only"] is True
    assert g["pregrade_live_actionability_audit_changes_trade_decisions"] is False
    assert g["zero_graded_current_release_rows_is_capture_failure"] is False
    assert g["current_release_capture_truth_read_from_canonical_decision_ledger"] is True
    assert g["live_capture_audit_backfills_history"] is False
    assert g["live_capture_audit_infers_missing_policy"] is False

    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert "apex_version: 69.10.0" in registry
    assert "pregrade_live_actionability_capture_audit" in registry
    assert "/api/triggers/actionability-capture-readiness" in registry

    routes = (ROOT / "engine/trigger_observatory_routes.py").read_text()
    assert '@app.get("/api/triggers/actionability-capture-readiness")' in routes


def test_dashboard_explains_pregrade_capture_truth():
    html = (ROOT / "templates/premium_discipline_command_center.html").read_text()
    assert "Pre-grade live capture:" in html
    assert "Zero graded current-release rows therefore no longer masquerades as a capture-wiring failure." in html
