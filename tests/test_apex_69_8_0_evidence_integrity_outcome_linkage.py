from __future__ import annotations

import json
from pathlib import Path

import engine.evidence_eligibility as eligibility_module
from engine.decision_reasoning_contracts import build_correlation_aware_consensus, build_engine_opinions
from engine.evidence_pipeline import _connect as evidence_connect
from engine.trigger_observatory import effectiveness, history, record_trigger, sync_canonical_outcomes

ROOT = Path(__file__).resolve().parents[1]


def test_eligibility_evaluator_failure_is_fail_closed(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise RuntimeError("eligibility unavailable")

    monkeypatch.setattr(eligibility_module, "evaluate_evidence_eligibility", boom)
    # Keep degradation persistence isolated from the repository working tree.
    monkeypatch.setenv("APEX_DEGRADATION_DB", str(tmp_path / "degradation.db"))

    opinions = build_engine_opinions({
        "institutional_intelligence": {"institutional_bias": "BULLISH", "confidence": 90},
        "flow_intelligence": {"flow_bias": "BULLISH", "confidence": 90},
        "market_state": {},
    })
    assert opinions
    assert all(o["eligibility_state"] == "INELIGIBLE" for o in opinions)
    assert all(o["eligibility_weight_factor"] == 0.0 for o in opinions)
    assert all(o["evidence_eligibility"]["consensus_eligible"] is False for o in opinions)
    assert all("ELIGIBILITY_EVALUATION_FAILED" in o["evidence_eligibility"]["reasons"] for o in opinions)

    consensus = build_correlation_aware_consensus(opinions)
    assert consensus["dominant_direction"] == "UNKNOWN"
    assert consensus["evidence_eligibility"]["consensus_eligible_count"] == 0
    assert sum(consensus["effective_directional_evidence"].values()) == 0.0


def test_trigger_links_to_canonical_grade_and_effectiveness_is_observational(tmp_path):
    trigger_db = str(tmp_path / "triggers.db")
    evidence_db = str(tmp_path / "evidence.db")
    decision_id = "decision-6980-1"

    out = record_trigger(
        source="CANONICAL_DECISION",
        trigger_type="ENTER_CALL",
        setup_family="FAILED_BREAKDOWN",
        symbol="SPX",
        direction="BULLISH",
        disposition="CONFIRMED",
        triggered_at="2026-08-30T14:35:00+00:00",
        source_event_key=decision_id,
        decision_id=decision_id,
        price=6500.0,
        path=trigger_db,
    )
    assert out["created"] is True

    with evidence_connect(evidence_db) as conn:
        conn.execute(
            """INSERT INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json)
               VALUES(?,?,?,?,?,?)""",
            (decision_id, "2026-08-30T14:40:01+00:00", "GRADED", None, 300,
             json.dumps({"won": True, "direction_correct": True, "mfe": 8.0, "mae": -2.0})),
        )
        conn.commit()

    linked = sync_canonical_outcomes(path=trigger_db, evidence_path=evidence_db)
    assert linked["linked"] == 1
    row = history(path=trigger_db)["triggers"][0]
    assert row["decision_id"] == decision_id
    assert row["canonical_grade_status"] == "GRADED"
    assert row["canonical_grade_label"] == "WIN"

    report = effectiveness(path=trigger_db)
    assert report["canonical_graded_links"] == 1
    assert report["groups"][0]["canonical_win_rate_pct"] == 100.0
    assert report["groups"][0]["behavioral_authority"] is False
    assert report["execution_authority"] is False
    assert report["production_effect"] == "OBSERVATIONAL_ONLY"


def test_69_8_0_guardrails_persist_in_current_release():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"]
    assert tuple(map(int, manifest["apex_version"].split("."))) >= (69, 8, 0)
    guardrails = manifest["guardrails"]
    assert guardrails["evidence_eligibility_failure_fails_closed"] is True
    assert guardrails["evidence_eligibility_failure_state"] == "INELIGIBLE"
    assert guardrails["evidence_eligibility_failure_weight_factor"] == 0.0
    assert guardrails["eligibility_failure_can_increase_authority"] is False
    assert guardrails["trigger_canonical_outcome_linkage"] is True
    assert guardrails["trigger_effectiveness_auto_promotes_policy"] is False
    assert guardrails["tick_momentum_promotion_in_69_8_0"] is False
    assert guardrails["microstructure_promotion_in_69_8_0"] is False

    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert "apex_version: 69.8.1" in registry
    assert "/api/triggers/effectiveness" in registry
    assert "eligibility_evaluator_failure_state: INELIGIBLE" in registry
    assert "canonical_module: engine.canonical_decision\n    status: compatibility" in registry
