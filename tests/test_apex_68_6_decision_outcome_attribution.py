from datetime import datetime, timedelta, timezone
import json

from engine.canonical_persistence import connection
from engine.decision_outcome_attribution import (
    capture_context, ensure_schema, grade_pending, initialize_store, summary,
)
from engine.evidence_pipeline import _connect


def _price_series(conn, ticker, start, values):
    for seconds, price in values:
        conn.execute(
            "INSERT INTO price_samples(ticker,observed_at,price) VALUES(?,?,?)",
            (ticker, (start + timedelta(seconds=seconds)).isoformat(), price),
        )


def test_abstention_counterfactual_is_separate_from_calibration_grades(tmp_path):
    db = tmp_path / "evidence.db"
    now = datetime(2026, 8, 22, 14, 0, tzinfo=timezone.utc)
    with _connect(db) as conn:
        snap = {
            "decision_id": "d-abstain", "timestamp": now.isoformat(), "ticker": "SPX",
            "session": "OPEN", "direction": "BULLISH", "action": "STAND_DOWN",
            "entry_reference": 6500.0, "confidence": 72.0, "learning_eligible": False,
            "multi_timeframe": {"decision_gate": "TIMEFRAME_CONFLICT"},
        }
        conn.execute(
            "INSERT INTO decisions(decision_id,observed_at,ticker,session,direction,action,entry_price,confidence,learning_eligible,snapshot_json,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("d-abstain", now.isoformat(), "SPX", "OPEN", "BULLISH", "STAND_DOWN", 6500.0, 72.0, 0, json.dumps(snap), "EXCLUDED"),
        )
        capture_context(conn, "d-abstain", now.isoformat(), snap)
        _price_series(conn, "SPX", now, [(30, 6501), (120, 6504), (240, 6508), (300, 6507)])
        conn.commit()
    out = grade_pending(db, horizon_seconds=300, now=now + timedelta(seconds=301))
    assert out["graded"] == 1
    with connection(db, read_only=True, wal=False, heal=False) as conn:
        attr = conn.execute("SELECT * FROM decision_effectiveness_attribution WHERE decision_id='d-abstain'").fetchone()
        assert attr["action_class"] == "ABSTAIN"
        assert attr["missed_opportunity"] == 1
        assert attr["mfe"] == 8.0
        # 68.6 must not insert abstention counterfactuals into calibration grading_results.
        assert conn.execute("SELECT COUNT(*) FROM grading_results WHERE decision_id='d-abstain'").fetchone()[0] == 0


def test_gate_effectiveness_reports_missed_after_block(tmp_path):
    db = tmp_path / "evidence.db"
    initialize_store(db)
    now = datetime(2026, 8, 22, 14, 0, tzinfo=timezone.utc)
    with _connect(db) as conn:
        snap = {
            "decision_id": "d-gate", "ticker": "SPX", "direction": "BEARISH", "action": "NO_TRADE",
            "entry_reference": 6500.0, "learning_eligible": False,
            "flow": {"decision_gate": "STAND_DOWN"},
        }
        conn.execute(
            "INSERT INTO decisions(decision_id,observed_at,ticker,session,direction,action,entry_price,confidence,learning_eligible,snapshot_json,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("d-gate", now.isoformat(), "SPX", "OPEN", "BEARISH", "NO_TRADE", 6500.0, 60, 0, json.dumps(snap), "EXCLUDED"),
        )
        capture_context(conn, "d-gate", now.isoformat(), snap)
        _price_series(conn, "SPX", now, [(60, 6498), (180, 6494), (300, 6492)])
        conn.commit()
    grade_pending(db, horizon_seconds=300, now=now + timedelta(seconds=301))
    report = summary(db)
    assert report["abstention_effectiveness"]["missed_opportunities"] == 1
    gate = next(x for x in report["gate_effectiveness"] if x["gate"].endswith("decision_gate"))
    assert gate["missed_after_block"] == 1
    assert gate["opportunity_cost_rate_pct"] == 100.0


def test_actionable_entry_quality_does_not_fabricate_late_entry(tmp_path):
    db = tmp_path / "evidence.db"
    now = datetime(2026, 8, 22, 14, 0, tzinfo=timezone.utc)
    with _connect(db) as conn:
        snap = {
            "decision_id": "d-action", "ticker": "SPX", "direction": "BULLISH", "action": "ENTER",
            "entry_reference": 6500.0, "learning_eligible": True,
            "quality_gate": {"decision_gate": "PASS"},
        }
        conn.execute(
            "INSERT INTO decisions(decision_id,observed_at,ticker,session,direction,action,entry_price,confidence,learning_eligible,snapshot_json,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("d-action", now.isoformat(), "SPX", "OPEN", "BULLISH", "ENTER", 6500.0, 75, 1, json.dumps(snap), "PENDING"),
        )
        capture_context(conn, "d-action", now.isoformat(), snap)
        _price_series(conn, "SPX", now, [(30, 6500.5), (120, 6503), (240, 6506), (300, 6505)])
        conn.commit()
    grade_pending(db, horizon_seconds=300, now=now + timedelta(seconds=301))
    report = summary(db)
    assert report["entry_effectiveness"]["classification_counts"]["OPTIMAL_ENTRY"] == 1
    assert report["entry_effectiveness"]["empirical_late_entry_inference_disabled"] is True


def test_initialize_store_is_idempotent(tmp_path):
    db = tmp_path / "evidence.db"
    assert initialize_store(db)["status"] == "READY"
    assert initialize_store(db)["status"] == "READY"
    report = summary(db)
    assert report["status"] == "READY"
    assert report["counts"]["captured"] == 0


def test_canonical_record_snapshot_hooks_attribution_without_changing_decision_contract(tmp_path):
    from engine.evidence_pipeline import record_snapshot
    db = tmp_path / "evidence.db"
    snap = {
        "decision_id": "hook-1", "timestamp": "2026-08-22T14:00:00+00:00", "ticker": "SPX",
        "session": "OPEN", "direction": "BULLISH", "action": "ENTER",
        "entry_reference": 6500.0, "confidence": 80.0, "learning_eligible": True,
    }
    assert record_snapshot(snap, db) is True
    with connection(db, read_only=True, wal=False, heal=False) as conn:
        decision = conn.execute("SELECT decision_id,status FROM decisions WHERE decision_id='hook-1'").fetchone()
        attr = conn.execute("SELECT decision_id,action_class,status FROM decision_effectiveness_attribution WHERE decision_id='hook-1'").fetchone()
    assert decision["status"] == "PENDING"
    assert attr["action_class"] == "ACTIONABLE"
    assert attr["status"] == "PENDING"


def test_initializer_backfills_existing_decision_context_without_outcomes(tmp_path):
    db = tmp_path / "evidence.db"
    with _connect(db) as conn:
        snap = {"decision_id":"legacy-1","ticker":"SPX","direction":"BULLISH","action":"STAND_DOWN","entry_reference":6500.0,"learning_eligible":False}
        conn.execute(
            "INSERT INTO decisions(decision_id,observed_at,ticker,session,direction,action,entry_price,confidence,learning_eligible,snapshot_json,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("legacy-1","2026-08-22T14:00:00+00:00","SPX","OPEN","BULLISH","STAND_DOWN",6500.0,55.0,0,json.dumps(snap),"EXCLUDED"),
        )
        conn.commit()
    out = initialize_store(db)
    assert out["backfilled_contexts"] == 1
    with connection(db, read_only=True, wal=False, heal=False) as conn:
        row = conn.execute("SELECT status,action_class FROM decision_effectiveness_attribution WHERE decision_id='legacy-1'").fetchone()
        assert row["status"] == "PENDING"
        assert row["action_class"] == "ABSTAIN"
        assert conn.execute("SELECT COUNT(*) FROM grading_results WHERE decision_id='legacy-1'").fetchone()[0] == 0


def test_outcome_grader_keeps_abstention_excluded_but_grades_attribution(tmp_path):
    from engine.outcome_grader import run_grader
    db = tmp_path / "evidence.db"
    start = datetime.now(timezone.utc) - timedelta(seconds=700)
    with _connect(db) as conn:
        snap = {"decision_id":"abstain-grader","ticker":"SPX","session":"OPEN","direction":"BULLISH","action":"NO_TRADE","entry_reference":6500.0,"learning_eligible":False}
        conn.execute(
            "INSERT INTO decisions(decision_id,observed_at,ticker,session,direction,action,entry_price,confidence,learning_eligible,snapshot_json,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("abstain-grader",start.isoformat(),"SPX","OPEN","BULLISH","NO_TRADE",6500.0,58.0,0,json.dumps(snap),"PENDING"),
        )
        capture_context(conn,"abstain-grader",start.isoformat(),snap)
        _price_series(conn,"SPX",start,[(60,6501),(180,6504),(300,6507)])
        conn.commit()
    out = run_grader(db,horizon_seconds=300)
    assert out["excluded"] == 1
    assert out["attribution"]["graded"] == 1
    with connection(db,read_only=True,wal=False,heal=False) as conn:
        grade=conn.execute("SELECT status,exclusion_reason FROM grading_results WHERE decision_id='abstain-grader'").fetchone()
        attr=conn.execute("SELECT status,missed_opportunity FROM decision_effectiveness_attribution WHERE decision_id='abstain-grader'").fetchone()
    assert grade["status"] == "EXCLUDED" and grade["exclusion_reason"] == "NON_ACTIONABLE"
    assert attr["status"] == "GRADED" and attr["missed_opportunity"] == 1
