from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from engine.evidence_pipeline import _connect as evidence_connect
from engine.trigger_observatory import (
    learning_readiness,
    record_canonical_snapshot,
    record_trigger,
    sync_canonical_outcomes,
    trade_visualization,
)

ROOT = Path(__file__).resolve().parents[1]


def _snapshot(*, decision_id: str = "decision-6982-1", score: float = 44.6):
    return {
        "timestamp": "2026-08-30T14:10:45+00:00",
        "ticker": "SPX",
        "market_state": {"price": 7709.9},
        "historical_evidence_capture": {"ok": True, "decision_id": decision_id},
        "institutional_decision_object": {
            "action": "NO_TRADE",
            "actionable": False,
            "direction": "BULLISH",
            "status": "FAIL_CLOSED",
            "raw_conviction": score,
            "conviction": {"score": score, "blocking_conditions": []},
        },
        "risk": {"target1": 7719.26, "target2": 7725.5},
    }


def test_canonical_trigger_uses_persisted_historical_decision_id_and_exposes_block_reason(tmp_path):
    db = str(tmp_path / "triggers.db")
    result = record_canonical_snapshot(_snapshot(), path=db)
    assert len(result["created"]) == 1
    view = trade_visualization(trigger_id=result["created"][0]["trigger_id"], path=db)["trade"]
    assert view["decision_id"] == "decision-6982-1"
    assert view["trigger_type"] == "NO_TRADE"
    assert view["disposition"] == "BLOCKED"
    assert "CONVICTION_BELOW_ACTIONABLE_THRESHOLD" in view["blockers"]
    assert "FAIL_CLOSED" in view["blockers"]
    assert view["is_actionable_trade"] is False


def test_explicit_canonical_decision_id_parameter_wins_over_snapshot_alias(tmp_path):
    db = str(tmp_path / "triggers.db")
    result = record_canonical_snapshot(
        _snapshot(decision_id="snapshot-id"),
        canonical_decision_id="persisted-id",
        path=db,
    )
    view = trade_visualization(trigger_id=result["created"][0]["trigger_id"], path=db)["trade"]
    assert view["decision_id"] == "persisted-id"


def test_canonical_grade_link_succeeds_with_propagated_decision_id(tmp_path):
    trigger_db = str(tmp_path / "triggers.db")
    evidence_db = str(tmp_path / "evidence.db")
    result = record_canonical_snapshot(_snapshot(decision_id="grade-link-id", score=70), path=trigger_db)
    with evidence_connect(evidence_db) as conn:
        conn.execute(
            "INSERT INTO decisions(decision_id,observed_at,ticker,learning_eligible,snapshot_json,status) VALUES(?,?,?,?,?,?)",
            ("grade-link-id", "2026-08-30T14:10:45+00:00", "SPX", 1, "{}", "GRADED"),
        )
        conn.execute(
            "INSERT INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json) VALUES(?,?,?,?,?,?)",
            ("grade-link-id", "2026-08-30T14:15:45+00:00", "GRADED", None, 300, json.dumps({"won": True, "mfe_points": 8.0, "mae_points": -1.0})),
        )
        conn.commit()
    linked = sync_canonical_outcomes(path=trigger_db, evidence_path=evidence_db)
    assert linked["linked"] == 1
    view = trade_visualization(trigger_id=result["created"][0]["trigger_id"], path=trigger_db)["trade"]
    assert view["canonical_grade_status"] == "GRADED"
    assert view["canonical_grade_label"] == "WIN"


def test_readiness_distinguishes_aggregate_threshold_from_activation_readiness(tmp_path, monkeypatch):
    evidence_db = str(tmp_path / "evidence.db")
    trigger_db = str(tmp_path / "triggers.db")
    monkeypatch.setenv("APEX_MIN_GRADED_HISTORY", "2")
    # Module constant is already imported in production code, so create enough rows for the
    # repository default as well; this verifies the distinction without changing policy.
    with evidence_connect(evidence_db) as conn:
        for i in range(55):
            did = f"d{i}"
            conn.execute(
                "INSERT INTO decisions(decision_id,observed_at,ticker,learning_eligible,snapshot_json,status) VALUES(?,?,?,?,?,?)",
                (did, "2026-08-30T14:00:00+00:00", "SPX", 1, "{}", "GRADED"),
            )
            conn.execute(
                "INSERT INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json) VALUES(?,?,?,?,?,?)",
                (did, "2026-08-30T14:05:00+00:00", "GRADED", None, 300, json.dumps({"won": bool(i % 2)})),
            )
        conn.commit()
    report = learning_readiness(evidence_path=evidence_db, trigger_path=trigger_db)
    assert report["calibration_eligible"] is True
    assert report["calibration_activation_state"] == "AGGREGATE_READY_BUCKETS_NOT_YET_ELIGIBLE"
    assert report["activation_eligible"] is False
    assert report["automatic_activation"] is False
    assert report["human_activation_required"] is True
    assert report["calibration_governance"]["eligibility_mode"] in {"HEURISTIC", "LEARNING"}


def test_observation_maturation_surfaces_overdue_open_trigger(tmp_path):
    evidence_db = str(tmp_path / "evidence.db")
    trigger_db = str(tmp_path / "triggers.db")
    with evidence_connect(evidence_db):
        pass
    record_trigger(
        source="CANONICAL_DECISION", trigger_type="NO_TRADE", symbol="SPX",
        direction="BULLISH", disposition="BLOCKED",
        triggered_at="2026-08-30T12:00:00+00:00", source_event_key="overdue",
        decision_id="overdue", price=6500.0, path=trigger_db,
    )
    report = learning_readiness(evidence_path=evidence_db, trigger_path=trigger_db)
    assert report["observation_maturation"]["observing"] == 1
    assert report["observation_maturation"]["overdue_observing"] == 1


def test_release_truth_and_6982_guardrails():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"]
    assert tuple(map(int, manifest["apex_version"].split("."))) >= (69, 8, 2)
    g = manifest["guardrails"]
    assert g["canonical_trigger_decision_id_propagation"] is True
    assert g["blocked_reason_visibility"] is True
    assert g["calibration_readiness_verification"] is True
    assert g["calibration_activation_automatic"] is False
    assert g["calibration_activation_human_governed"] is True
    assert g["trigger_observation_maturation_diagnostic"] is True
    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert f"apex_version: {manifest['apex_version']}" in registry
    assert "calibration_readiness_verification" in registry


def test_dashboard_surfaces_linkage_activation_and_maturation_state():
    html = (ROOT / "templates/premium_discipline_command_center.html").read_text()
    assert "Decision ${esc(t.decision_id||'UNLINKED')}" in html
    assert "Calibration Mode" in html
    assert "Active Calibrations" in html
    assert "Overdue Observing" in html
    assert "Automatic activation remains disabled" in html
