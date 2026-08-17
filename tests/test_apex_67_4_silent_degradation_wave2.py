from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXPECTED = {
    "engine/execution_intelligence_core_v260.py": [
        "risk_limits_provider", "entry_optimization", "position_sizing",
        "contract_intelligence", "liquidity_slippage",
    ],
    "engine/position_sizing_v264.py": ["risk_limits_provider"],
    "engine/daily_key_levels.py": ["hlce_enrichment"],
    "signal_evaluator.py": ["outcome_mark_callback"],
    "engine/learning_calibration.py": [
        "ensure_store", "persist_policy_proposal", "last_signal_provider",
    ],
    "engine/institutional_validation_promotion_v255.py": ["governance_audit"],
    "engine/range_routes.py": ["capture_projection"],
    "engine/execution_os_routes.py": [
        "last_result_provider", "session_provider", "risk_config_provider",
    ],
    "engine/historical_level_calibration.py": ["prune_old_samples"],
}


def test_wave2_high_consequence_paths_emit_structured_degradations():
    missing = []
    for rel, operations in EXPECTED.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "record_degradation" in text
        for op in operations:
            if f'operation="{op}"' not in text:
                missing.append((rel, op))
    assert missing == []


def test_execution_fallbacks_mark_authority_suppression():
    text = (ROOT / "engine/execution_intelligence_core_v260.py").read_text()
    assert text.count("decision_authority_suppressed=True") >= 5
    sizing = (ROOT / "engine/position_sizing_v264.py").read_text()
    assert "decision_authority_suppressed=True" in sizing
    eos = (ROOT / "engine/execution_os_routes.py").read_text()
    assert eos.count("decision_authority_suppressed=True") >= 3


def test_wave2_is_observability_only_release():
    import json
    m = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert m["apex_version"] == "67.4.0"
    assert m["guardrails"]["degradation_observability_changes_decisions"] is False
    assert m["guardrails"]["degradation_observability_changes_execution_authority"] is False
