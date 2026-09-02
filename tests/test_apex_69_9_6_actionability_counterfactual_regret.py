from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from engine.evidence_pipeline import _connect
from engine.historical_evidence_lifecycle import build_snapshot
from engine.trigger_observatory import (
    counterfactual_regret_validation,
    observe_price,
    predictive_validation,
    record_trigger,
)

ROOT = Path(__file__).resolve().parents[1]


def _decision(conn, *, did: str, observed_at: str, won: bool = True,
              actionability: dict | None = None, direction: str = "BEARISH"):
    snap = {
        "action": "NO_TRADE",
        "actionable": False,
        "execution_actionable": False,
        "observational_learning_eligible": True,
        "direction": direction,
        "apex_release_version": "69.9.6",
    }
    if actionability is not None:
        snap["counterfactual_actionability"] = actionability
    conn.execute(
        """INSERT INTO decisions(decision_id,observed_at,ticker,session,direction,action,
           entry_price,confidence,learning_eligible,snapshot_json,status)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (did, observed_at, "SPX", "MARKET_OPEN", direction, "NO_TRADE",
         6500.0, 65.0, 1, json.dumps(snap), "GRADED"),
    )
    conn.execute(
        """INSERT INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json)
           VALUES(?,?,?,?,?,?)""",
        (did, observed_at, "GRADED", None, 300,
         json.dumps({"won": won, "direction_correct": won, "horizon_seconds": 300})),
    )


def _actionability(*, cutoff_passed: bool | None = False, session_present: bool = True,
                   thesis_state: str = "INVALIDATED", blockers=None,
                   conviction: float = 65.0, recommendation_action=None):
    return {
        "schema_version": "apex.counterfactual_actionability_capture.v1",
        "capture_version": "69.9.6",
        "session_intelligence_present": session_present,
        "session_mode": "ATTACK" if session_present else None,
        "entry_cutoff_et": "11:30" if session_present else None,
        "cutoff_passed": cutoff_passed if session_present else None,
        "market_session": "MARKET_OPEN",
        "trade_guidance_enabled": True,
        "thesis_state": thesis_state,
        "direction": "BEARISH",
        "conviction_score": conviction,
        "blocking_conditions": list(blockers or []),
        "ido_actionable": False,
        "ido_status": "THESIS_INVALIDATED" if thesis_state == "INVALIDATED" else "FAIL_CLOSED",
        "recommendation_action": recommendation_action,
        "recommendation_state": None,
        "final_action": "NO_TRADE",
        "entry_reference_available": True,
        "targets_and_decision_levels": {},
        "dynamic_policy_state": "NORMAL",
        "dynamic_policy_blocking_conditions": [],
        "source_truth": "FINALIZED_DECISION_TIME_SNAPSHOT",
        "historical_policy_inference": False,
    }


def _trigger(trigger_db: Path, *, did: str, ts: str, blockers, target1: float | None = 6497.0):
    rec = record_trigger(
        source="CANONICAL_DECISION", trigger_type="NO_TRADE", direction="BEARISH",
        disposition="BLOCKED", triggered_at=ts, price=6500.0, entry=6500.0,
        target1=target1, blockers=blockers, decision_id=did, source_event_key=did,
        path=str(trigger_db),
    )
    with sqlite3.connect(trigger_db) as conn:
        conn.execute(
            """UPDATE observed_trade_triggers SET canonical_grade_status='GRADED',
               canonical_grade_label='WIN',canonical_grade_json=?,canonical_graded_at=?
               WHERE trigger_id=?""",
            (json.dumps({"won": True}), ts, rec["trigger_id"]),
        )
    return rec["trigger_id"]


def test_historical_snapshot_persists_exact_actionability_window_inputs():
    result = {
        "session": "MARKET_OPEN",
        "session_intelligence": {
            "session": {
                "mode": "ATTACK", "cutoff": "11:30", "cutoff_passed": False,
            }
        },
        "recommendation": {"action": "NO_TRADE", "state": "WATCH"},
        "institutional_decision_object": {
            "ticker": "SPX", "timestamp": "2026-09-01T14:00:00+00:00",
            "action": "NO_TRADE", "direction": "BEARISH", "actionable": False,
            "status": "THESIS_INVALIDATED",
            "market_state": {"price": 6500.0},
            "market_narrative": {"trade_guidance_enabled": True},
            "institutional_thesis": {"state": "INVALIDATED", "dominant_direction": "BEARISH"},
            "conviction": {"score": 65.0, "blocking_conditions": []},
            "targets_and_decision_levels": {"tp1": 6497.0},
        },
    }
    snap = build_snapshot(result, session_state="MARKET_OPEN")
    a = snap["counterfactual_actionability"]
    assert tuple(map(int, str(a["capture_version"]).split("."))) >= (69, 9, 6)
    assert a["session_intelligence_present"] is True
    assert a["session_mode"] == "ATTACK"
    assert a["entry_cutoff_et"] == "11:30"
    assert a["cutoff_passed"] is False
    assert a["trade_guidance_enabled"] is True
    assert a["thesis_state"] == "INVALIDATED"
    assert a["recommendation_action"] == "NO_TRADE"
    assert a["historical_policy_inference"] is False


def test_actionability_qualified_regret_requires_persisted_window_and_no_independent_disqualifier(tmp_path):
    trigger_db = tmp_path / "triggers.db"
    evidence_db = tmp_path / "evidence.db"
    ts = "2026-09-01T14:00:00+00:00"  # 10:00 ET
    with _connect(evidence_db) as conn:
        _decision(conn, did="eligible", observed_at=ts, actionability=_actionability())
    _trigger(trigger_db, did="eligible", ts=ts, blockers=["THESIS_INVALIDATED"])
    observe_price(symbol="SPX", price=6496.0, observed_at="2026-09-01T14:01:00+00:00", path=str(trigger_db))

    out = predictive_validation(path=str(trigger_db), evidence_path=str(evidence_db))
    cf = out["counterfactual_regret"]
    assert cf["state_counts"]["POTENTIAL_BLOCKER_REGRET"] == 1
    row = cf["by_blocker_session"][0]
    assert row["blocker"] == "THESIS_INVALIDATED"
    assert row["counterfactual_trade_eligible"] == 1
    assert row["potential_blocker_regret"] == 1
    assert row["actionability_window_evidence_available"] == 1


def test_persisted_cutoff_passed_blocks_regret_even_when_move_hits_target(tmp_path):
    trigger_db = tmp_path / "triggers.db"
    evidence_db = tmp_path / "evidence.db"
    ts = "2026-09-01T16:00:00+00:00"  # 12:00 ET
    with _connect(evidence_db) as conn:
        _decision(conn, did="late", observed_at=ts, actionability=_actionability(cutoff_passed=True))
    _trigger(trigger_db, did="late", ts=ts, blockers=["THESIS_INVALIDATED"])
    observe_price(symbol="SPX", price=6496.0, observed_at="2026-09-01T16:01:00+00:00", path=str(trigger_db))

    cf = predictive_validation(path=str(trigger_db), evidence_path=str(evidence_db))["counterfactual_regret"]
    assert cf["state_counts"].get("POTENTIAL_BLOCKER_REGRET", 0) == 0
    assert cf["reason_counts"]["OUTSIDE_ACTIONABILITY_WINDOW"] == 1
    assert cf["by_blocker_session"][0]["counterfactual_trade_eligible"] == 0


def test_current_cutoff_reference_never_backfills_missing_historical_window(tmp_path):
    trigger_db = tmp_path / "triggers.db"
    evidence_db = tmp_path / "evidence.db"
    ts = "2026-09-01T17:30:00+00:00"  # 13:30 ET, beyond current default cutoff
    with _connect(evidence_db) as conn:
        _decision(conn, did="legacy", observed_at=ts, actionability=_actionability(session_present=False))
    _trigger(trigger_db, did="legacy", ts=ts, blockers=["THESIS_INVALIDATED"])
    observe_price(symbol="SPX", price=6496.0, observed_at="2026-09-01T17:31:00+00:00", path=str(trigger_db))

    cf = predictive_validation(path=str(trigger_db), evidence_path=str(evidence_db))["counterfactual_regret"]
    assert cf["reason_counts"]["ACTIONABILITY_WINDOW_EVIDENCE_UNAVAILABLE"] == 1
    assert cf["by_blocker_session"][0]["current_policy_reference_past_cutoff"] == 1
    assert cf["qualification_contract"]["current_policy_reference_can_backfill_historical_actionability"] is False
    assert cf["current_policy_clock_reference"]["historical_qualification_uses_reference"] is False


def test_second_blocker_is_independent_disqualifier_for_targeted_blocker_regret(tmp_path):
    trigger_db = tmp_path / "triggers.db"
    evidence_db = tmp_path / "evidence.db"
    ts = "2026-09-01T14:00:00+00:00"
    with _connect(evidence_db) as conn:
        _decision(conn, did="multi", observed_at=ts, actionability=_actionability())
    _trigger(
        trigger_db, did="multi", ts=ts,
        blockers=["THESIS_INVALIDATED", "CONVICTION_BELOW_ACTIONABLE_THRESHOLD"],
    )
    observe_price(symbol="SPX", price=6496.0, observed_at="2026-09-01T14:01:00+00:00", path=str(trigger_db))

    cf = predictive_validation(path=str(trigger_db), evidence_path=str(evidence_db))["counterfactual_regret"]
    targeted = next(x for x in cf["by_blocker_session"] if x["blocker"] == "THESIS_INVALIDATED")
    assert targeted["potential_blocker_regret"] == 0
    assert targeted["reason_counts"]["INDEPENDENT_DISQUALIFIER_PRESENT"] == 1


def test_no_explicit_blocker_diagnostic_identifies_recommendation_layer_no_trade(tmp_path):
    trigger_db = tmp_path / "triggers.db"
    evidence_db = tmp_path / "evidence.db"
    ts = "2026-09-01T14:00:00+00:00"
    a = _actionability(thesis_state="ACTIVE", recommendation_action="NO_TRADE")
    a["ido_status"] = "ACTIONABLE"
    a["ido_actionable"] = True
    with _connect(evidence_db) as conn:
        _decision(conn, did="no-blocker", observed_at=ts, actionability=a)
    _trigger(trigger_db, did="no-blocker", ts=ts, blockers=[])
    observe_price(symbol="SPX", price=6496.0, observed_at="2026-09-01T14:01:00+00:00", path=str(trigger_db))

    cf = counterfactual_regret_validation(path=str(trigger_db), evidence_path=str(evidence_db))["counterfactual_regret"]
    diag = cf["no_explicit_blocker_diagnostics"]
    assert diag["sample_size"] == 1
    assert diag["recommendation_layer_no_trade"] == 1
    assert diag["potential_blocker_regret"] == 0
    assert diag["reason_counts"]["RECOMMENDATION_LAYER_NO_TRADE"] == 1
    assert diag["unexplained_no_trade_with_passing_captured_gates"] == 0


def test_release_truth_and_guardrails_are_69_9_6():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"]
    assert tuple(map(int, manifest["apex_version"].split("."))) >= (69, 9, 6)
    g = manifest["guardrails"]
    assert g["counterfactual_regret_observational_only"] is True
    assert g["historical_actionability_requires_persisted_decision_time_window"] is True
    assert g["current_cutoff_reference_backfills_historical_actionability"] is False
    assert g["counterfactual_regret_requires_no_independent_disqualifier"] is True
    assert g["counterfactual_regret_changes_trade_decisions"] is False
    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert f"apex_version: {manifest['apex_version']}" in registry
    assert "/api/triggers/counterfactual-regret" in registry
    assert "counterfactual_regret_qualification" in registry
    routes = (ROOT / "engine/trigger_observatory_routes.py").read_text()
    assert '@app.get("/api/triggers/counterfactual-regret")' in routes


def test_dashboard_surfaces_actionability_qualification_truth():
    html = (ROOT / "templates/premium_discipline_command_center.html").read_text()
    assert "Counterfactual Trade Eligibility" in html
    assert "ACTIONABILITY_WINDOW_EVIDENCE_UNAVAILABLE" in html
    assert "current cutoff is reference-only" in html
    assert "noExplicitBlockerRows" in html
