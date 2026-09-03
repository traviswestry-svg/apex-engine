from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from engine.evidence_pipeline import _connect
from engine.execution.trade_risk_guard import RiskLimits, entry_window_policy_snapshot
from engine.historical_evidence_lifecycle import build_snapshot
from engine.trigger_observatory import observe_price, predictive_validation, record_trigger

ROOT = Path(__file__).resolve().parents[1]


def _scanner_result(*, ts: str, recommendation="ENTER PUT NOW", session_intelligence=None):
    result = {
        "session": "MARKET_OPEN",
        "recommendation": recommendation,
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
    if session_intelligence is not None:
        result["session_intelligence"] = session_intelligence
    return result


def _persist_snapshot(conn, *, did: str, ts: str, snapshot: dict, won: bool = True):
    snapshot = dict(snapshot)
    snapshot["decision_id"] = did
    snapshot["apex_release_version"] = snapshot.get("apex_release_version") or "69.9.7"
    conn.execute(
        """INSERT INTO decisions(decision_id,observed_at,ticker,session,direction,action,
           entry_price,confidence,learning_eligible,snapshot_json,status)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            did, ts, "SPX", "MARKET_OPEN", "BEARISH", "NO_TRADE",
            6500.0, 65.0, 1, json.dumps(snapshot), "GRADED",
        ),
    )
    conn.execute(
        """INSERT INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json)
           VALUES(?,?,?,?,?,?)""",
        (did, ts, "GRADED", None, 300, json.dumps({"won": won, "direction_correct": won, "horizon_seconds": 300})),
    )


def _trigger(trigger_db: Path, *, did: str, ts: str):
    rec = record_trigger(
        source="CANONICAL_DECISION",
        trigger_type="NO_TRADE",
        direction="BEARISH",
        disposition="BLOCKED",
        triggered_at=ts,
        price=6500.0,
        entry=6500.0,
        target1=6497.0,
        blockers=["THESIS_INVALIDATED"],
        decision_id=did,
        source_event_key=did,
        path=str(trigger_db),
    )
    with sqlite3.connect(trigger_db) as conn:
        conn.execute(
            """UPDATE observed_trade_triggers
               SET canonical_grade_status='GRADED',canonical_grade_label='WIN',
                   canonical_grade_json=?,canonical_graded_at=?
               WHERE trigger_id=?""",
            (json.dumps({"won": True}), ts, rec["trigger_id"]),
        )
    return rec["trigger_id"]


def test_entry_window_policy_snapshot_uses_exact_risk_guard_policy(monkeypatch):
    monkeypatch.setenv("TRADE_NO_NEW_AFTER_ET", "11:30")
    before = entry_window_policy_snapshot(
        now=__import__("datetime").datetime.fromisoformat("2026-09-02T14:00:00+00:00"),
        session_state="MARKET_OPEN",
    )
    after = entry_window_policy_snapshot(
        now=__import__("datetime").datetime.fromisoformat("2026-09-02T16:00:00+00:00"),
        session_state="MARKET_OPEN",
    )
    assert before["source_environment_key"] == "TRADE_NO_NEW_AFTER_ET"
    assert before["entry_cutoff_et"] == "11:30"
    assert before["cutoff_passed"] is False
    assert before["entry_window_authorized"] is True
    assert after["cutoff_passed"] is True
    assert after["entry_window_authorized"] is False
    assert RiskLimits.from_env().no_new_trades_after_et == before["entry_cutoff_et"]


def test_scanner_shaped_snapshot_without_phase11_captures_live_entry_policy(monkeypatch):
    monkeypatch.setenv("TRADE_NO_NEW_AFTER_ET", "11:30")
    snap = build_snapshot(_scanner_result(ts="2026-09-02T14:00:00+00:00"), session_state="MARKET_OPEN")
    a = snap["counterfactual_actionability"]
    assert a["schema_version"] == "apex.counterfactual_actionability_capture.v2"
    assert tuple(map(int, a["capture_version"].split("."))) >= (69, 9, 7)
    assert a["session_intelligence_present"] is False
    assert a["entry_window_source"] == "TRADE_RISK_GUARD_POLICY"
    assert a["entry_window_source_present"] is True
    assert a["entry_cutoff_et"] == "11:30"
    assert a["cutoff_passed"] is False
    assert a["entry_window_authorized"] is True
    assert a["recommendation_action"] == "ENTER PUT NOW"
    assert a["recommendation_source"] == "result.recommendation(string)"
    assert a["trade_guidance_enabled"] is True
    assert a["thesis_state"] == "INVALIDATED"
    assert a["conviction_score"] == 65.0
    assert a["capture_provenance"]["entry_cutoff_et"]["status"] == "DERIVED_FROM_DECISION_TIME_POLICY"
    assert a["capture_provenance"]["cutoff_passed"]["status"] == "DERIVED_FROM_DECISION_TIME_POLICY"
    assert a["capture_provenance"]["recommendation_action"]["status"] == "SOURCE_PRESENT"
    assert a["capture_provenance"]["session_mode"]["status"] == "SOURCE_PATH_NOT_FOUND"


def test_session_intelligence_precedes_risk_policy_when_present(monkeypatch):
    monkeypatch.setenv("TRADE_NO_NEW_AFTER_ET", "11:30")
    result = _scanner_result(
        ts="2026-09-02T14:00:00+00:00",
        recommendation={"action": "NO_TRADE", "state": "WATCH"},
        session_intelligence={"session": {"mode": "DEFENSE", "cutoff": "11:15", "cutoff_passed": False}},
    )
    a = build_snapshot(result, session_state="MARKET_OPEN")["counterfactual_actionability"]
    assert a["entry_window_source"] == "SESSION_INTELLIGENCE"
    assert a["entry_cutoff_et"] == "11:15"
    assert a["cutoff_passed"] is False
    assert a["session_mode"] == "DEFENSE"
    assert a["recommendation_action"] == "NO_TRADE"
    assert a["recommendation_state"] == "WATCH"
    assert a["capture_provenance"]["entry_cutoff_et"]["status"] == "SOURCE_PRESENT"


def test_risk_policy_wired_capture_can_qualify_counterfactual_without_phase11(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_NO_NEW_AFTER_ET", "11:30")
    trigger_db = tmp_path / "triggers.db"
    evidence_db = tmp_path / "evidence.db"
    ts = "2026-09-02T14:00:00+00:00"  # 10:00 ET
    snap = build_snapshot(_scanner_result(ts=ts), session_state="MARKET_OPEN")
    with _connect(evidence_db) as conn:
        _persist_snapshot(conn, did="wired", ts=ts, snapshot=snap, won=True)
    _trigger(trigger_db, did="wired", ts=ts)
    observe_price(symbol="SPX", price=6496.0, observed_at="2026-09-02T14:01:00+00:00", path=str(trigger_db))

    cf = predictive_validation(path=str(trigger_db), evidence_path=str(evidence_db))["counterfactual_regret"]
    assert cf["schema_version"] in {"apex.counterfactual_regret_qualification.v2", "apex.counterfactual_regret_qualification.v3"}
    assert cf["state_counts"]["POTENTIAL_BLOCKER_REGRET"] == 1
    row = cf["by_blocker_session"][0]
    assert row["actionability_window_evidence_available"] == 1
    assert row["counterfactual_trade_eligible"] == 1
    readiness = cf["actionability_capture_readiness"]
    assert readiness["status"] == "CURRENT_RELEASE_READY"
    assert readiness["current_release_rows"] == 1
    assert readiness["current_release_entry_window_evidence_available"] == 1
    assert readiness["entry_window_source_counts"]["TRADE_RISK_GUARD_POLICY"] == 1


def test_risk_policy_wired_capture_closes_after_cutoff(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_NO_NEW_AFTER_ET", "11:30")
    trigger_db = tmp_path / "triggers.db"
    evidence_db = tmp_path / "evidence.db"
    ts = "2026-09-02T16:00:00+00:00"  # 12:00 ET
    snap = build_snapshot(_scanner_result(ts=ts), session_state="MARKET_OPEN")
    assert snap["counterfactual_actionability"]["cutoff_passed"] is True
    with _connect(evidence_db) as conn:
        _persist_snapshot(conn, did="late", ts=ts, snapshot=snap, won=True)
    _trigger(trigger_db, did="late", ts=ts)
    observe_price(symbol="SPX", price=6496.0, observed_at="2026-09-02T16:01:00+00:00", path=str(trigger_db))
    cf = predictive_validation(path=str(trigger_db), evidence_path=str(evidence_db))["counterfactual_regret"]
    assert cf["state_counts"].get("POTENTIAL_BLOCKER_REGRET", 0) == 0
    assert cf["reason_counts"]["OUTSIDE_ACTIONABILITY_WINDOW"] == 1


def test_release_truth_and_guardrails_are_69_9_7():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"]
    assert tuple(map(int, manifest["apex_version"].split("."))) >= (69, 9, 7)
    g = manifest["guardrails"]
    assert g["decision_time_entry_risk_policy_capture_observational_only"] is True
    assert g["entry_risk_policy_capture_changes_risk_limits"] is False
    assert g["historical_actionability_requires_persisted_decision_time_window"] is True
    assert g["legacy_actionability_current_cutoff_backfill"] is False
    assert g["actionability_capture_field_provenance_required"] is True
    assert g["string_recommendation_capture_supported"] is True
    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert f"apex_version: {manifest['apex_version']}" in registry
    assert "decision_time_entry_risk_policy_capture" in registry
    assert "actionability_capture_readiness" in registry


def test_dashboard_surfaces_capture_readiness():
    html = (ROOT / "templates/premium_discipline_command_center.html").read_text()
    assert "Actionability capture:" in html
    assert "risk-guard source" in html
    assert "CURRENT_RELEASE_READY" in html
    assert "Legacy history is never backfilled" in html
