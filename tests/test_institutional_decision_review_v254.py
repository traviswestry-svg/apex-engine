"""Tests for APEX 25.4 Institutional Decision Review & Learning Engine."""
import datetime as dt

import pytest

from engine import institutional_decision_review_v254 as review


def _iso(offset_s=0):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=offset_s)).isoformat()


def _snapshot(direction="BULLISH", confidence=82, eligibility_ok=True):
    now = _iso()
    return {
        "as_of": now, "symbol": "SPX", "decision_id": "dec_review_001",
        "direction": direction, "confidence": confidence, "market_regime": "TREND",
        "setup_family": "opening_drive",
        "market_state": {"spx": 5200.0, "as_of": now, "bias": direction, "regime": "TREND"},
        "institutional_intelligence": {"as_of": now, "institutional_bias": direction, "ici_score": 78},
        "flow_intelligence": {"as_of": now, "direction": direction, "score": 72},
        "dealer_positioning": {"as_of": now, "bias": direction},
        "multi_timeframe": {"as_of": now, "alignment_score": 70},
        "market_memory": {"as_of": now}, "historical_similarity": {"as_of": now},
        "confidence_calibration": {"as_of": now},
    }


def _realized(won=True, direction="BULLISH", **kw):
    base = {
        "matured": True, "taken": True, "won": won,
        "realized_direction": direction, "realized_move_points": 12.0,
        "realized_mfe": 12.0, "realized_mae": 4.0, "target_hit": won,
        "invalidated": not won, "realized_path": [5200, 5205, 5212],
        "adverse_before_favorable": False, "realized_scenario": "base",
    }
    base.update(kw)
    return base


# --------------------------------------------------------------------------- #
# Status / lifecycle
# --------------------------------------------------------------------------- #
def test_status_advisory_no_self_modification():
    s = review.status()
    assert s["production_effect"] == "NONE"
    assert s["uncontrolled_self_modification"] is False
    assert s["production_change_requires_approval"] is True
    assert "NOT_GRADEABLE" in s["grades"]


def test_lifecycle_snapshot_has_full_provenance():
    lc = review.build_lifecycle_snapshot(_snapshot())
    for key in ("decision_id", "evidence_health", "thesis", "counter_thesis",
                "forecast", "engine_versions", "confidence_waterfall"):
        assert key in lc
    assert lc["engine_versions"]["review"] == review.VERSION


# --------------------------------------------------------------------------- #
# Grading: reproducible, decision-quality not outcome-direction
# --------------------------------------------------------------------------- #
def test_grade_is_reproducible():
    lc = review.build_lifecycle_snapshot(_snapshot())
    r1 = review.review_decision(lc, _realized())
    r2 = review.review_decision(lc, _realized())
    r1.pop("generated_at"); r2.pop("generated_at")
    assert r1 == r2


def test_losing_outcome_not_automatically_bad():
    # Strong process, but the trade lost -> should be flagged as adverse variance,
    # not automatically graded F.
    lc = review.build_lifecycle_snapshot(_snapshot(confidence=80))
    r = review.review_decision(lc, _realized(won=False))
    assert r["review_grade"] != "F" or r["outcome_luck_flag"] == "SOUND_DECISION_ADVERSE_OUTCOME"
    assert r["graded_on"] == "DECISION_QUALITY_NOT_OUTCOME_DIRECTION"


def test_winning_outcome_not_automatically_good():
    # Weak process (missing critical evidence) but the trade won -> luck flag.
    snap = _snapshot(confidence=40)
    snap.pop("market_state")
    snap.pop("institutional_intelligence")
    lc = review.build_lifecycle_snapshot(snap)
    r = review.review_decision(lc, _realized(won=True))
    if r["gradeable"]:
        assert r["process_score"] is not None
        # process should not be inflated to A just because it won
        assert r["review_grade"] in review.GRADES


def test_not_gradeable_when_outcome_missing():
    lc = review.build_lifecycle_snapshot(_snapshot())
    r = review.review_decision(lc, None)
    assert r["review_grade"] == "NOT_GRADEABLE"
    assert r["gradeable"] is False


def test_not_gradeable_when_immature():
    lc = review.build_lifecycle_snapshot(_snapshot())
    r = review.review_decision(lc, {"matured": False})
    assert r["review_grade"] == "NOT_GRADEABLE"


def test_decomposition_has_eight_dimensions():
    lc = review.build_lifecycle_snapshot(_snapshot())
    r = review.review_decision(lc, _realized())
    for key in review.DECOMPOSITION_KEYS:
        assert key in r["decomposition"]
        assert r["decomposition"][key] is not None


# --------------------------------------------------------------------------- #
# Error attribution
# --------------------------------------------------------------------------- #
def test_wrong_direction_attributed():
    lc = review.build_lifecycle_snapshot(_snapshot(direction="BULLISH"))
    r = review.review_decision(lc, _realized(won=False, direction="BEARISH"))
    assert "WRONG_DIRECTIONAL_THESIS" in r["error_attribution"]


def test_confidence_overstated_attributed():
    lc = review.build_lifecycle_snapshot(_snapshot(confidence=90))
    r = review.review_decision(lc, _realized(won=False, direction="BULLISH"))
    assert "CONFIDENCE_OVERSTATED" in r["error_attribution"]


def test_stale_data_attributed():
    snap = _snapshot()
    snap["flow_intelligence"]["as_of"] = _iso(-100000)  # stale non-critical source
    lc = review.build_lifecycle_snapshot(snap)
    r = review.review_decision(lc, _realized(won=False))
    assert "STALE_DATA" in r["error_attribution"]


# --------------------------------------------------------------------------- #
# Recommendations + governed workflow
# --------------------------------------------------------------------------- #
def test_recommendations_have_required_fields():
    lc = review.build_lifecycle_snapshot(_snapshot(confidence=90))
    r = review.review_decision(lc, _realized(won=False))
    recos = review.generate_recommendations(r, lc)
    assert recos
    for reco in recos:
        for field in ("recommendation_id", "status", "affected_component", "proposed_change",
                      "expected_benefit", "risks", "rollback_plan", "created_at"):
            assert field in reco
        assert reco["status"] == "PROPOSED"


def test_workflow_transitions(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_DECISION_REVIEW_DB", str(tmp_path / "r.db"))
    lc = review.build_lifecycle_snapshot(_snapshot(confidence=90))
    r = review.review_decision(lc, _realized(won=False))
    recos = review.generate_recommendations(r, lc)
    review.store_recommendations(recos)
    rid = recos[0]["recommendation_id"]
    approved = review.approve_recommendation(rid, actor="travis")
    assert approved["ok"] is True
    assert approved["new_status"] == "APPROVED"
    assert approved["production_effect"] == "NONE"
    listed = review.list_recommendations(status="APPROVED")
    assert any(x["recommendation_id"] == rid for x in listed["recommendations"])


# --------------------------------------------------------------------------- #
# Replay fidelity
# --------------------------------------------------------------------------- #
def test_replay_reconstructs_from_stored_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_DECISION_REVIEW_DB", str(tmp_path / "r.db"))
    lc = review.build_lifecycle_snapshot(_snapshot())
    review.record_decision(lifecycle=lc)
    realized = _realized()
    r = review.review_decision(lc, realized)
    review.persist_review(lc["decision_id"], r, realized)
    replayed = review.replay(lc["decision_id"])
    assert replayed["ok"] is True
    assert replayed["reconstructed_from"] == "stored_snapshot"
    assert replayed["thesis"] == lc["thesis"]
    assert replayed["confidence_state"]["ceiling"] == lc["confidence_ceiling"]
    assert replayed["actual_path"] == realized["realized_path"]


def test_replay_missing_decision():
    assert review.replay("nonexistent")["ok"] is False


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
def test_reports_all_kinds(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_DECISION_REVIEW_DB", str(tmp_path / "r.db"))
    for kind in review.REPORT_KINDS:
        rep = review.build_report(kind)
        assert rep["ok"] is True
        assert rep["report"] == kind


def test_report_unknown_kind():
    assert review.build_report("does_not_exist")["ok"] is False


# --------------------------------------------------------------------------- #
# Mission Control + build_review
# --------------------------------------------------------------------------- #
def test_build_review_full():
    result = review.build_review(_snapshot(), realized=_realized())
    assert result["ok"] is True
    assert result["production_effect"] == "NONE"
    assert result["guardrails"]["uncontrolled_self_modification"] is False
    group = review.mission_control_group(result)
    assert group["group"] == "DECISION_REVIEW"
    assert group["production_effect"] == "NONE"
