from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from engine.evidence_pipeline import _connect
from engine.trigger_observatory import abstention_regret_validation, predictive_validation, record_trigger

ROOT = Path(__file__).resolve().parents[1]


def _decision(conn, *, did: str, session: str, won: bool, threshold: float | None = None):
    snap = {
        "action": "NO_TRADE",
        "actionable": False,
        "execution_actionable": False,
        "observational_learning_eligible": True,
        "apex_release_version": "69.9.4",
    }
    if threshold is not None:
        snap["dynamic_state_policy"] = {
            "state": "NORMAL",
            "required_boundary_margin_points": threshold,
            "modifiers": [],
        }
    conn.execute(
        """INSERT INTO decisions(decision_id,observed_at,ticker,session,direction,action,
           entry_price,confidence,learning_eligible,snapshot_json,status)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            did, "2026-08-31T13:35:00+00:00", "SPX", session, "BEARISH",
            "NO_TRADE", 6500.0, 65.0, 1, json.dumps(snap), "GRADED",
        ),
    )
    conn.execute(
        """INSERT INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json)
           VALUES(?,?,?,?,?,?)""",
        (
            did, "2026-08-31T13:40:00+00:00", "GRADED", None, 300,
            json.dumps({"won": won, "direction_correct": won}),
        ),
    )


def _trigger(trigger_db: Path, *, did: str, session_time: str, won: bool,
             target1: float | None = None, blockers=None, confidence: float = 65.0,
             mfe: float = 0.0, mae: float = 0.0):
    rec = record_trigger(
        source="CANONICAL_DECISION",
        trigger_type="NO_TRADE",
        direction="BEARISH",
        disposition="BLOCKED",
        triggered_at=session_time,
        confidence=confidence,
        price=6500.0,
        entry=6500.0,
        target1=target1,
        blockers=blockers or ["THESIS_INVALIDATED"],
        decision_id=did,
        source_event_key=did,
        path=str(trigger_db),
    )
    with sqlite3.connect(trigger_db) as conn:
        conn.execute(
            """UPDATE observed_trade_triggers
               SET canonical_grade_status='GRADED',
                   canonical_grade_label=?,
                   outcome_label=?,
                   mfe_points=?,
                   mae_points=?
               WHERE trigger_id=?""",
            (
                "WIN" if won else "LOSS",
                "FAVORABLE" if won else "ADVERSE",
                mfe,
                -abs(mae),
                rec["trigger_id"],
            ),
        )
    return rec["trigger_id"]


def _obs(conn, trigger_id: str, at: str, favorable: float, adverse: float):
    conn.execute(
        """INSERT INTO trade_trigger_price_observations(
           observation_id,trigger_id,observed_at,price,favorable_points,adverse_points,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (
            f"{trigger_id}-{at}",
            trigger_id,
            at,
            6500.0,
            favorable,
            adverse,
            at,
        ),
    )


def test_session_conditioned_abstention_regret_and_timing(tmp_path):
    trigger_db = tmp_path / "triggers.db"
    evidence_db = tmp_path / "evidence.db"

    with _connect(evidence_db) as conn:
        _decision(conn, did="pre-loss", session="PREMARKET", won=False)
        _decision(conn, did="open-regret", session="MARKET_OPEN", won=True)
        _decision(conn, did="open-correct-unproven", session="MARKET_OPEN", won=True)

    pre = _trigger(
        trigger_db, did="pre-loss", session_time="2026-08-31T12:45:00+00:00",
        won=False, blockers=["THESIS_INVALIDATED"], confidence=75.0, mfe=0.5, mae=3.0,
    )
    regret = _trigger(
        trigger_db, did="open-regret", session_time="2026-08-31T13:35:00+00:00",
        won=True, target1=6497.0, blockers=["THESIS_INVALIDATED"], confidence=65.0,
        mfe=4.0, mae=1.0,
    )
    unproven = _trigger(
        trigger_db, did="open-correct-unproven", session_time="2026-08-31T13:50:00+00:00",
        won=True, blockers=["THESIS_INVALIDATED", "CONVICTION_BELOW_ACTIONABLE_THRESHOLD"],
        confidence=65.0, mfe=2.0, mae=0.5,
    )

    with sqlite3.connect(trigger_db) as conn:
        _obs(conn, regret, "2026-08-31T13:35:30+00:00", 0.5, 0.0)
        _obs(conn, regret, "2026-08-31T13:36:00+00:00", 0.0, -1.0)
        _obs(conn, regret, "2026-08-31T13:37:00+00:00", 3.0, 0.0)
        _obs(conn, unproven, "2026-08-31T13:50:45+00:00", 1.0, 0.0)

    out = predictive_validation(path=str(trigger_db), evidence_path=str(evidence_db))
    ar = out["abstention_regret"]

    assert ar["population_contract"] == "CANONICAL_OBSERVATIONAL_NO_TRADE_ONLY"
    assert ar["sample_size"] == 3
    assert ar["classification_counts"]["ABSTENTION_SUCCESS"] == 1
    assert ar["classification_counts"]["POTENTIAL_BLOCKER_REGRET"] == 1
    assert ar["classification_counts"]["DIRECTIONALLY_CORRECT_BUT_NOT_PROVEN_TRADEABLE"] == 1

    overall = ar["overall"]
    assert overall["canonical_graded"] == 3
    assert overall["blocked_thesis_directionally_correct"] == 2
    assert overall["blocked_thesis_directionally_incorrect"] == 1
    assert overall["abstention_success_rate_pct"] == 33.33
    assert overall["potential_blocker_regret"] == 1
    assert overall["movement_threshold_evaluable"] == 1
    assert overall["movement_threshold_met"] == 1
    assert overall["movement_threshold_sources"]["PERSISTED_TARGET1_REFERENCE"] == 1
    assert overall["movement_threshold_sources"]["UNAVAILABLE"] == 2

    blocker_session = {
        (x["blocker"], x["session"]): x
        for x in ar["by_blocker_session"]
    }
    assert blocker_session[("THESIS_INVALIDATED", "PREMARKET")]["abstention_success_rate_pct"] == 100.0
    assert blocker_session[("THESIS_INVALIDATED", "MARKET_OPEN")]["potential_blocker_regret"] == 1

    multiplicity = {
        (x["blocker_multiplicity"], x["session"]): x
        for x in ar["by_blocker_multiplicity_session"]
    }
    assert multiplicity[("ISOLATED_BLOCKER", "MARKET_OPEN")]["canonical_graded"] == 1
    assert multiplicity[("SIMULTANEOUS_BLOCKERS", "MARKET_OPEN")]["canonical_graded"] == 1

    windows = {
        (x["market_open_elapsed_bucket"], x["blocker"]): x
        for x in ar["market_open_elapsed"]
        if x["market_open_elapsed_bucket"] != "NOT_MARKET_OPEN"
    }
    assert windows[("OPENING_0_15", "THESIS_INVALIDATED")]["potential_blocker_regret"] == 1
    assert ("OPENING_15_30", "THESIS_INVALIDATED") in windows

    # Persisted observation timing only: no interpolation.
    open_group = blocker_session[("THESIS_INVALIDATED", "MARKET_OPEN")]
    assert open_group["time_to_favorable_observed"] == 2
    assert open_group["time_to_threshold_favorable_observed"] == 1
    assert open_group["avg_time_to_threshold_favorable_seconds"] == 120.0


def test_governed_margin_can_make_regret_evaluable_without_fabricated_default(tmp_path):
    trigger_db = tmp_path / "triggers.db"
    evidence_db = tmp_path / "evidence.db"
    with _connect(evidence_db) as conn:
        _decision(conn, did="governed", session="MARKET_OPEN", won=True, threshold=5.0)
        _decision(conn, did="missing", session="MARKET_OPEN", won=True, threshold=None)

    governed_id = _trigger(
        trigger_db, did="governed", session_time="2026-08-31T14:05:00+00:00",
        won=True, blockers=["THESIS_INVALIDATED"], confidence=65.0, mfe=5.5, mae=1.0,
    )
    missing_id = _trigger(
        trigger_db, did="missing", session_time="2026-08-31T14:10:00+00:00",
        won=True, blockers=["THESIS_INVALIDATED"], confidence=65.0, mfe=20.0, mae=1.0,
    )
    with sqlite3.connect(trigger_db) as conn:
        _obs(conn, governed_id, "2026-08-31T14:06:00+00:00", 5.5, -1.0)
        _obs(conn, missing_id, "2026-08-31T14:11:00+00:00", 20.0, -1.0)

    out = predictive_validation(path=str(trigger_db), evidence_path=str(evidence_db))
    overall = out["abstention_regret"]["overall"]
    assert overall["movement_threshold_evaluable"] == 1
    assert overall["potential_blocker_regret"] == 1
    assert overall["directionally_correct_but_not_proven_tradeable"] == 1
    assert overall["movement_threshold_sources"]["DYNAMIC_STATE_POLICY_REQUIRED_BOUNDARY_MARGIN"] == 1
    assert overall["movement_threshold_sources"]["UNAVAILABLE"] == 1
    assert out["abstention_regret"]["movement_threshold_contract"]["missing_threshold_behavior"] == "NOT_EVALUABLE_NO_INFERENCE"


def test_abstention_regret_endpoint_wrapper_preserves_authority_boundaries(tmp_path):
    trigger_db = tmp_path / "triggers.db"
    evidence_db = tmp_path / "evidence.db"
    out = abstention_regret_validation(path=str(trigger_db), evidence_path=str(evidence_db))
    assert out["behavioral_authority"] is False
    assert out["execution_authority"] is False
    assert out["broker_mutation"] is False
    assert out["production_effect"] == "OBSERVATIONAL_ONLY"


def test_release_truth_and_guardrails_are_69_9_4():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"]
    assert tuple(map(int, manifest["apex_version"].split("."))) >= (69, 9, 4)
    g = manifest["guardrails"]
    assert g["abstention_regret_observational_only"] is True
    assert g["abstention_regret_changes_trade_decisions"] is False
    assert g["abstention_regret_changes_blockers"] is False
    assert g["potential_blocker_regret_is_not_execution_proof"] is True
    assert g["movement_threshold_requires_persisted_source"] is True
    assert g["movement_threshold_missing_values_inferred"] is False
    assert g["observation_timing_uses_persisted_samples_only"] is True
    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert f"apex_version: {manifest['apex_version']}" in registry
    assert "/api/triggers/abstention-regret" in registry
    assert "session_conditioned_abstention_regret" in registry
    routes = (ROOT / "engine/trigger_observatory_routes.py").read_text()
    assert '@app.get("/api/triggers/abstention-regret")' in routes


def test_dashboard_surfaces_abstention_regret_without_execution_claims():
    html = (ROOT / "templates/premium_discipline_command_center.html").read_text()
    assert "Session-Conditioned Abstention Regret" in html
    assert "Potential blocker regret" in html
    assert "Market Open Window × Blocker" in html
    assert "Blocker Multiplicity × Session" in html
    assert "not proof that an executable SPXW trade existed" in html
