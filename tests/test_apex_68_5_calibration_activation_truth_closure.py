import json
from pathlib import Path

import engine.evidence_pipeline as evidence_pipeline
from engine.evidence_pipeline import _connect, record_snapshot
from engine.dynamic_state_calibration_governance import create_candidate, review_candidate
from engine.calibration_activation import activate_candidate, rollback_activation, activation_status, eligibility_readout
from engine.dynamic_state_policy import evaluate_dynamic_state_policy
from engine.post_persistence_architecture_audit import snapshot as persistence_snapshot

ROOT = Path(__file__).resolve().parents[1]


def _snap(did, phase):
    return {
        "decision_id": did,
        "timestamp": "2026-08-22T14:00:00+00:00",
        "ticker": "SPX", "session": "RTH", "direction": "BULLISH", "action": "WATCH",
        "entry_reference": 6400.0, "confidence": 75.0, "learning_eligible": True,
        "decision_quality": {"alert_quality": {"state": "WATCH_ONLY"}, "dynamic_state_policy": {
            "version": "68.2.0", "state": "WATCH_ONLY", "threshold_adjustment_points": 4,
            "conviction_penalty_points": 4, "consensus_penalty_points": 0,
            "watch_only": True, "suppress_new_alerts": False, "modifiers": [],
        }},
        "dynamic_state": {
            "event_phase": {"phase": phase},
            "gamma_term_structure": {"term_divergence": False, "near_term_fragility": False},
            "residual_pressure": {"unresolved": False},
            "flow_excitation": {"independent_evidence_factor": 1.0},
        },
    }


def _grade(db, did, won):
    with _connect(db) as conn:
        conn.execute(
            "INSERT INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json) VALUES(?,?,?,?,?,?)",
            (did, "2026-08-22T14:10:00+00:00", "GRADED", None, 300,
             json.dumps({"won": won, "direction_correct": won, "mfe": 3 if won else 1,
                         "mae": -1 if won else -4, "directional_move": 2 if won else -2})),
        )


def _seed(db, n=30):
    for i in range(n):
        did = f"c{i}"
        record_snapshot(_snap(did, "PRE_EVENT"), db)
        _grade(db, did, i < 6)
    for i in range(n):
        did = f"i{i}"
        record_snapshot(_snap(did, "NORMAL"), db)
        _grade(db, did, i < 24)


def test_release_truth_preserves_68_5_series():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert tuple(map(int, manifest["apex_version"].split("."))) >= (68, 5, 0)
    assert manifest["guardrails"]["calibration_activation_human_approval_required"] is True
    assert manifest["guardrails"]["calibration_activation_changes_execution_authority"] is False
    assert "apex_version: 69.0." in registry
    assert "governed_calibration_activation:" in registry


def test_root_app_direct_sqlite_is_closed_and_audit_scope_includes_app():
    app = (ROOT / "app.py").read_text()
    assert "sqlite3.connect(" not in app
    assert "canonical_sqlite_connect(DB_PATH" in app
    assert "canonical_sqlite_connect(SPINE_DB_PATH" in app
    assert "canonical_sqlite_connect(REVIEW_DB_PATH" in app
    snap = persistence_snapshot()
    assert "app.py" in snap["audit_scope"]
    assert not any(x["module"] == "app.py" for x in snap["persistence"]["direct_sqlite_sites"])


def test_loop_closure_requires_approval_then_activation_and_is_rollbackable(tmp_path, monkeypatch):
    db = tmp_path / "e.db"
    _seed(db)
    monkeypatch.setattr(evidence_pipeline, "DEFAULT_DB", str(db))
    c = create_candidate(
        db, dimension="event_phase", challenger_bucket="PRE_EVENT", incumbent_bucket="NORMAL",
        expected_relation="LOWER", proposal={"threshold_adjustment_points": 1.0}, actor="TEST",
        min_sample=20, min_effective_sample=15, min_delta_pp=5, max_p_value=0.10,
    )
    assert c["status"] == "ELIGIBLE_FOR_REVIEW"

    blocked = activate_candidate(db, c["candidate_id"], actor="SYSTEM_ARCHITECTURE", reason="too early")
    assert blocked["ok"] is False

    reviewed = review_candidate(db, c["candidate_id"], decision="APPROVE", actor="SYSTEM_ARCHITECTURE", note="validated")
    assert reviewed["status"] == "APPROVED"
    activated = activate_candidate(db, c["candidate_id"], actor="TRADING_LOGIC", reason="bounded production trial")
    assert activated["status"] == "ACTIVE"
    assert activated["automatic_activation"] is False

    ds = {
        "available": True,
        "event_phase": {"phase": "PRE_EVENT"},
        "flow_excitation": {"available": False},
        "residual_pressure": {"available": False},
        "gamma_term_structure": {"available": False},
        "gamma_path": {"available": False},
    }
    live = evaluate_dynamic_state_policy({"direction": "BULLISH"}, dynamic_state=ds)
    assert live["threshold_adjustment_points"] == 4.0  # base PRE_EVENT 3 + governed 1
    assert live["calibration_activation"]["active"] is True
    assert live["suppress_new_alerts"] is False
    assert live["watch_only"] is False

    rolled = rollback_activation(db, activated["activation_id"], actor="RISK_CONTROLS", reason="test rollback")
    assert rolled["status"] == "ROLLED_BACK"
    after = evaluate_dynamic_state_policy({"direction": "BULLISH"}, dynamic_state=ds)
    assert after["threshold_adjustment_points"] == 3.0
    assert after["calibration_activation"]["active"] is False
    assert activation_status(db)["active_count"] == 0
    assert eligibility_readout(db)["status"] == "APPROVED"


def test_activation_rejects_out_of_bounds_adjustment(tmp_path):
    db = tmp_path / "e.db"
    _seed(db)
    c = create_candidate(
        db, dimension="event_phase", challenger_bucket="PRE_EVENT", incumbent_bucket="NORMAL",
        expected_relation="LOWER", proposal={"threshold_adjustment_points": 10.0}, actor="TEST",
        min_sample=20, min_effective_sample=15, min_delta_pp=5, max_p_value=0.10,
    )
    review_candidate(db, c["candidate_id"], decision="APPROVE", actor="SYSTEM_ARCHITECTURE", note="reviewed")
    out = activate_candidate(db, c["candidate_id"], actor="TRADING_LOGIC", reason="should block")
    assert out["ok"] is False
    assert out["status"] == "POLICY_BOUNDS_BLOCKED"


def test_calibration_cannot_change_event_suppression(tmp_path, monkeypatch):
    db = tmp_path / "e.db"
    monkeypatch.setattr(evidence_pipeline, "DEFAULT_DB", str(db))
    ds = {
        "available": True,
        "event_phase": {"phase": "EVENT_IMMINENT"},
        "flow_excitation": {"available": False}, "residual_pressure": {"available": False},
        "gamma_term_structure": {"available": False}, "gamma_path": {"available": False},
    }
    out = evaluate_dynamic_state_policy({"direction": "BULLISH"}, dynamic_state=ds)
    assert out["state"] == "SUPPRESSED"
    assert out["suppress_new_alerts"] is True
