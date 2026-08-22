import json

from engine.evidence_pipeline import _connect, record_snapshot
from engine.dynamic_state_calibration_governance import (
    assess_candidate,
    compare_buckets,
    create_candidate,
    governance_overview,
    review_candidate,
    wilson_interval,
)


def _snap(did, phase, ief=1.0):
    return {
        "decision_id": did,
        "timestamp": "2026-08-21T14:00:00+00:00",
        "ticker": "SPX", "session": "RTH", "direction": "BULLISH", "action": "WATCH",
        "entry_reference": 6400.0, "confidence": 75.0, "learning_eligible": True,
        "decision_quality": {"alert_quality": {"state": "WATCH_ONLY"}, "dynamic_state_policy": {
            "version": "68.2.0", "state": "WATCH_ONLY", "threshold_adjustment_points": 4,
            "conviction_penalty_points": 4, "consensus_penalty_points": 0,
            "watch_only": True, "suppress_new_alerts": False, "modifiers": [],
        }},
        "dynamic_state": {
            "event_phase": {"phase": phase},
            "gamma_term_structure": {"term_divergence": False, "near_term_fragility": False, "immediate_regime": "POSITIVE"},
            "gamma_path": {"path_version": "p1", "level_version": "l1", "current_regime": "POSITIVE"},
            "residual_pressure": {"unresolved": False},
            "flow_excitation": {"independent_evidence_factor": ief},
        },
    }


def _grade(db, did, won):
    with _connect(db) as conn:
        conn.execute("INSERT INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json) VALUES(?,?,?,?,?,?)",
                     (did,"2026-08-21T14:10:00+00:00","GRADED",None,300,json.dumps({"won":won,"direction_correct":won,"mfe":3 if won else 1,"mae":-1 if won else -4,"directional_move":2 if won else -2})))


def _seed(db, *, n=30, challenger_wins=6, incumbent_wins=24, ief=1.0):
    for i in range(n):
        did=f"c{i}"; record_snapshot(_snap(did,"PRICE_DISCOVERY",ief),db); _grade(db,did,i<challenger_wins)
    for i in range(n):
        did=f"i{i}"; record_snapshot(_snap(did,"NORMAL",ief),db); _grade(db,did,i<incumbent_wins)


def test_wilson_interval_is_bounded_and_not_point_estimate():
    ci=wilson_interval(8,10)
    assert 0 <= ci["lower_pct"] < 80 < ci["upper_pct"] <= 100


def test_compare_requires_independent_effective_sample(tmp_path):
    db=tmp_path/"e.db"
    _seed(db,n=30,challenger_wins=6,incumbent_wins=24,ief=0.2)
    out=compare_buckets(db,"event_phase","PRICE_DISCOVERY","NORMAL",expected_relation="LOWER",min_sample=20,min_effective_sample=15)
    assert out["integrity_gates"]["raw_sample"] is True
    assert out["integrity_gates"]["independent_effective_sample"] is False
    assert out["eligible_for_review"] is False
    assert "MINIMUM_INDEPENDENT_EFFECTIVE_SAMPLE_NOT_MET" in out["blockers"]


def test_candidate_becomes_eligible_only_when_integrity_gates_pass(tmp_path):
    db=tmp_path/"e.db"
    _seed(db,n=30,challenger_wins=6,incumbent_wins=24,ief=1.0)
    c=create_candidate(db,dimension="event_phase",challenger_bucket="PRICE_DISCOVERY",incumbent_bucket="NORMAL",
                       expected_relation="LOWER",proposal={"threshold_adjustment_points": 2},actor="TEST",
                       min_sample=20,min_effective_sample=15,min_delta_pp=5,max_p_value=0.10)
    assert c["status"] == "ELIGIBLE_FOR_REVIEW"
    a=assess_candidate(db,c["candidate_id"])
    assert a["assessment"]["integrity_gates"]["statistical_significance"] is True
    assert a["assessment"]["delta_win_rate_pp"] < 0


def test_approval_is_human_and_has_no_production_effect(tmp_path):
    db=tmp_path/"e.db"
    _seed(db,n=30,challenger_wins=6,incumbent_wins=24,ief=1.0)
    c=create_candidate(db,dimension="event_phase",challenger_bucket="PRICE_DISCOVERY",incumbent_bucket="NORMAL",
                       expected_relation="LOWER",proposal={"threshold_adjustment_points": 2},actor="TEST",
                       min_sample=20,min_effective_sample=15)
    r=review_candidate(db,c["candidate_id"],decision="APPROVE",actor="SYSTEM_ARCHITECTURE",note="reviewed")
    assert r["status"] == "APPROVED"
    assert r["production_effect"] == "NONE"
    assert r["handoff_required"] is True
    assert r["handoff_target"] == "engine.production_governance"
    ov=governance_overview(db)
    assert ov["counts"]["APPROVED"] == 1
    assert ov["governance"]["automatic_production_activation"] is False


def test_collecting_candidate_cannot_be_approved(tmp_path):
    db=tmp_path/"e.db"
    _seed(db,n=4,challenger_wins=1,incumbent_wins=3,ief=1.0)
    c=create_candidate(db,dimension="event_phase",challenger_bucket="PRICE_DISCOVERY",incumbent_bucket="NORMAL",
                       expected_relation="LOWER",proposal={"threshold_adjustment_points": 2},actor="TEST")
    assert c["status"] == "COLLECTING"
    r=review_candidate(db,c["candidate_id"],decision="APPROVE",actor="SYSTEM_ARCHITECTURE")
    assert r["ok"] is False
    assert r["status"] == "COLLECTING"
