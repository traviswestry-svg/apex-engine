import os
import sqlite3
import pytest
from engine import trade_director_institutional_evidence as ev


def context(state="ARMED", confidence=88):
    return {"symbol":"SPX", "checked_at":"2026-07-23T14:00:00+00:00", "trade_id":"T-31",
            "decision_state":state, "direction":"CALL", "confidence":confidence,
            "entry_price":6300.0, "stop_price":6294.0, "target_price":6312.0,
            "feature_vector":{"gamma":{"state":"POSITIVE"},"flow":{"score":72}},
            "confidence_attribution":{"dealer":30,"flow":25,"price":33}}


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_EVIDENCE_DB", str(tmp_path / "evidence.db"))
    ev.initialize_evidence_store()


def test_non_actionable_decision_is_not_captured():
    result=ev.capture_decision(context("OBSERVE"))
    assert result["captured"] is False and result["state"]=="NOT_ACTIONABLE"


def test_actionable_snapshot_is_immutable_and_idempotent():
    first=ev.capture_decision(context()); second=ev.capture_decision(context())
    assert first["captured"] and second["duplicate"]
    assert first["decision"]["snapshot_hash"]
    with sqlite3.connect(ev.evidence_db_path()) as conn:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE apex_evidence_decisions SET confidence=1")


def test_feature_vector_and_attribution_are_frozen():
    result=ev.capture_decision(context())["decision"]
    assert result["feature_vector"]["gamma"]["state"]=="POSITIVE"
    assert result["engine_attribution"]["dealer"]==30


def test_target_hit_grades_win():
    decision=ev.capture_decision(context())["decision"]
    bars=[{"timestamp":"2026-07-23T14:01:00Z","open":6300,"high":6306,"low":6298,"close":6304},
          {"timestamp":"2026-07-23T14:02:00Z","open":6304,"high":6313,"low":6303,"close":6311}]
    out=ev.grade_decision(decision["decision_id"],bars)["outcome"]
    assert out["grade"]=="WIN" and out["target_hit"] and out["realized_points"]==12


def test_same_bar_target_and_stop_is_conservative_ambiguous():
    decision=ev.capture_decision(context())["decision"]
    out=ev.grade_decision(decision["decision_id"],[{"timestamp":"x","open":6300,"high":6313,"low":6293,"close":6305}])["outcome"]
    assert out["grade"]=="AMBIGUOUS"
    assert out["exit_reason"]=="AMBIGUOUS_SAME_BAR_STOP_FIRST"
    assert out["realized_points"]==-6


def test_grading_is_idempotent_and_outcomes_immutable():
    decision=ev.capture_decision(context())["decision"]
    bars=[{"timestamp":"x","open":6300,"high":6305,"low":6299,"close":6304}]
    ev.grade_decision(decision["decision_id"],bars)
    assert ev.grade_decision(decision["decision_id"],bars)["duplicate"] is True
    with sqlite3.connect(ev.evidence_db_path()) as conn:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM apex_evidence_outcomes")


def test_confidence_calibration_uses_only_graded_decisions():
    d=ev.capture_decision(context(confidence=88))["decision"]
    ev.grade_decision(d["decision_id"],[{"timestamp":"x","open":6300,"high":6313,"low":6299,"close":6312}])
    summary=ev.calibration_summary()
    band=next(b for b in summary["bands"] if b["band"]=="85-100")
    assert summary["graded_decisions"]==1 and band["win_rate_pct"]==100.0
    assert summary["policy_mutation_enabled"] is False


def test_integrity_chain_verifies():
    d=ev.capture_decision(context())["decision"]
    ev.grade_decision(d["decision_id"],[{"timestamp":"x","open":6300,"high":6302,"low":6298,"close":6301}])
    assert ev.verify_evidence_integrity()["status"]=="VERIFIED"


def test_status_stays_evidence_gated_before_100_outcomes():
    status=ev.build_institutional_evidence(context(),auto_capture=True)
    assert status["decision_count"]==1
    assert "FEWER_THAN_100_GRADED_DECISIONS" in status["blockers"]
    assert status["controls"]["automatic_weight_updates"] is False
