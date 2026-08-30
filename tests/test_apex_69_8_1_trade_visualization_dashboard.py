from __future__ import annotations

import json
from pathlib import Path

from engine.evidence_pipeline import _connect as evidence_connect
from engine.trigger_observatory import (
    learning_readiness,
    observe_price,
    record_trigger,
    trade_visualization,
)

ROOT = Path(__file__).resolve().parents[1]


def test_trade_visualization_uses_only_persisted_path_and_marks_levels(tmp_path):
    db = str(tmp_path / "triggers.db")
    out = record_trigger(
        source="CANONICAL_DECISION",
        trigger_type="ENTER_CALL",
        setup_family="FAILED_BREAKDOWN",
        symbol="SPX",
        direction="BULLISH",
        disposition="CONFIRMED",
        triggered_at="2026-08-30T14:35:00+00:00",
        source_event_key="decision-6981-1",
        decision_id="decision-6981-1",
        price=6500.0,
        entry=6500.0,
        stop=6495.0,
        target1=6505.0,
        target2=6510.0,
        target3=6515.0,
        confidence=78,
        path=db,
    )
    observe_price(symbol="SPX", price=6503.0, observed_at="2026-08-30T14:36:00+00:00", path=db)
    observe_price(symbol="SPX", price=6506.0, observed_at="2026-08-30T14:40:01+00:00", path=db)

    view = trade_visualization(trigger_id=out["trigger_id"], path=db)
    trade = view["trade"]
    assert view["status"] == "READY"
    assert trade["entry"] == 6500.0
    assert trade["tp1"] == 6505.0
    assert trade["target_hits"]["tp1"] is True
    assert trade["target_hits"]["tp2"] is False
    assert trade["stop_hit"] is False
    assert [x["price"] for x in trade["observations"]] == [6503.0, 6506.0]
    assert trade["is_actionable_trade"] is True
    assert trade["observational_only"] is True
    assert view["execution_authority"] is False
    assert view["broker_mutation"] is False


def test_trade_visualization_does_not_fabricate_premium(tmp_path):
    db = str(tmp_path / "triggers.db")
    out = record_trigger(
        source="CANONICAL_DECISION", trigger_type="NO_TRADE", symbol="SPX",
        direction="BULLISH", disposition="BLOCKED", source_event_key="blocked-1",
        decision_id="blocked-1", price=6500.0, evidence={}, path=db,
    )
    trade = trade_visualization(trigger_id=out["trigger_id"], path=db)["trade"]
    assert trade["premium"]["available"] is False
    assert trade["premium"]["source"] == "UNAVAILABLE"
    assert trade["is_actionable_trade"] is False


def test_learning_readiness_is_read_only_and_reports_progress(tmp_path):
    evidence_db = str(tmp_path / "evidence.db")
    with evidence_connect(evidence_db) as conn:
        conn.execute(
            "INSERT INTO decisions(decision_id,observed_at,ticker,learning_eligible,snapshot_json,status) VALUES(?,?,?,?,?,?)",
            ("d1", "2026-08-30T14:35:00+00:00", "SPX", 1, "{}", "GRADED"),
        )
        conn.execute(
            "INSERT INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json) VALUES(?,?,?,?,?,?)",
            ("d1", "2026-08-30T14:40:00+00:00", "GRADED", None, 300, json.dumps({"won": True})),
        )
        conn.commit()
    r = learning_readiness(evidence_path=evidence_db)
    assert r["graded_outcomes"] == 1
    assert r["minimum_graded"] >= 1
    assert r["progress_pct"] > 0
    assert r["behavioral_authority"] is False
    assert r["execution_authority"] is False


def test_premium_command_center_contains_trade_and_learning_surfaces():
    html = (ROOT / "templates/premium_discipline_command_center.html").read_text()
    assert "APEX Trade Visualization" in html
    assert "Trigger Effectiveness & Learning Readiness" in html
    assert "/api/triggers/trade-view" in html
    assert "/api/triggers/learning-readiness" in html
    assert "PREMIUM DATA UNAVAILABLE" in html
    assert "OBSERVATIONAL DISPLAY ONLY" in html


def test_release_truth_is_69_8_1_and_authority_is_unchanged():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"] == "69.8.1"
    assert manifest["build_name"] == "Premium Discipline Trade Visualization & Learning Readiness Command Center"
    g = manifest["guardrails"]
    assert g["premium_discipline_trade_visualization"] is True
    assert g["trade_visualization_observational_only"] is True
    assert g["trade_visualization_uses_persisted_trigger_prices_only"] is True
    assert g["premium_values_fabricated"] is False
    assert g["trade_visualization_changes_trade_decisions"] is False
    assert g["trade_visualization_changes_execution_authority"] is False
    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert "apex_version: 69.8.1" in registry
    assert "/api/triggers/trade-view" in registry
    assert "/api/triggers/learning-readiness" in registry
