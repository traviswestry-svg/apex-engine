import json

from engine.evidence_pipeline import _connect, record_snapshot
from engine.dynamic_state_outcome_calibration import (
    calibration_summary,
    extract_context,
    ensure_schema,
)


def _snapshot(did="d1", phase="PRICE_DISCOVERY", divergence=True, residual_opposes=True, ief=0.2):
    modifiers=[]
    if residual_opposes:
        modifiers.append({"driver":"residual_pressure","effect":"OPPOSES"})
    return {
        "decision_id": did,
        "timestamp": "2026-08-21T14:00:00+00:00",
        "ticker": "SPX",
        "session": "RTH",
        "direction": "BULLISH",
        "action": "WATCH",
        "entry_reference": 6400.0,
        "confidence": 82.0,
        "learning_eligible": True,
        "decision_quality": {
            "alert_quality": {"state": "WATCH_ONLY"},
            "dynamic_state_policy": {
                "version":"68.2.0","state":"WATCH_ONLY","threshold_adjustment_points":8,
                "conviction_penalty_points":8,"consensus_penalty_points":0,
                "watch_only":True,"suppress_new_alerts":False,"modifiers":modifiers,
                "warnings":["POST_EVENT_PRICE_DISCOVERY"],"blocking_conditions":[],
            },
        },
        "dynamic_state": {
            "event_phase": {"phase": phase, "event_name":"FOMC","minutes_to_event":-2},
            "gamma_term_structure": {"term_divergence": divergence, "near_term_fragility": divergence, "immediate_regime":"POSITIVE"},
            "gamma_path": {"path_version":"p1","level_version":"l1","current_regime":"POSITIVE"},
            "residual_pressure": {"unresolved":True,"direction":"BEARISH","remaining_pressure":65},
            "flow_excitation": {"independent_evidence_factor":ief},
        },
    }


def test_extract_context_freezes_policy_drivers():
    c=extract_context(_snapshot())
    assert c["event_phase"] == "PRICE_DISCOVERY"
    assert c["gamma_term_divergence"] is True
    assert c["residual_pressure_opposes"] is True
    assert c["flow_independence_bucket"] == "HIGHLY_REDUNDANT"
    assert c["alert_state"] == "WATCH_ONLY"
    assert c["threshold_adjustment_points"] == 8.0


def test_record_snapshot_persists_immutable_dynamic_context(tmp_path):
    db=tmp_path/"evidence.db"
    assert record_snapshot(_snapshot(), db) is True
    changed=_snapshot()
    changed["dynamic_state"]["event_phase"]["phase"]="NORMAL"
    assert record_snapshot(changed, db) is False
    with _connect(db) as conn:
        ensure_schema(conn)
        row=conn.execute("SELECT context_json FROM dynamic_state_decision_context WHERE decision_id='d1'").fetchone()
    context=json.loads(row["context_json"])
    assert context["event_phase"] == "PRICE_DISCOVERY"


def test_calibration_summary_joins_existing_outcomes(tmp_path):
    db=tmp_path/"evidence.db"
    for i in range(4):
        phase="NORMAL" if i < 2 else "PRICE_DISCOVERY"
        snap=_snapshot(f"d{i}", phase=phase, divergence=i>=2, residual_opposes=i>=2, ief=0.9 if i<2 else 0.2)
        record_snapshot(snap, db)
    with _connect(db) as conn:
        for i in range(4):
            won=i<2
            outcome={"won":won,"direction_correct":won,"directional_move":3 if won else -2,"mfe":5 if won else 1,"mae":-1 if won else -4}
            conn.execute("INSERT INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json) VALUES(?,?,?,?,?,?)",
                         (f"d{i}","2026-08-21T14:10:00+00:00","GRADED",None,300,json.dumps(outcome)))
    out=calibration_summary(db,min_sample=2)
    assert out["graded_contexts"] == 4
    phases={x["bucket"]:x for x in out["dimensions"]["event_phase"]}
    assert phases["NORMAL"]["win_rate_pct"] == 100.0
    assert phases["PRICE_DISCOVERY"]["win_rate_pct"] == 0.0
    assert phases["NORMAL"]["calibration_ready"] is True
    assert out["governance"]["automatic_threshold_mutation"] is False


def test_calibration_not_ready_below_minimum(tmp_path):
    db=tmp_path/"evidence.db"
    record_snapshot(_snapshot(), db)
    with _connect(db) as conn:
        conn.execute("INSERT INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json) VALUES(?,?,?,?,?,?)",
                     ("d1","2026-08-21T14:10:00+00:00","GRADED",None,300,json.dumps({"won":True,"mfe":1,"mae":-1,"directional_move":1})))
    out=calibration_summary(db,min_sample=20)
    assert out["status"] == "COLLECTING"
    assert out["dimensions"]["event_phase"][0]["calibration_ready"] is False
