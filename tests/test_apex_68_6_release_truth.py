import json
from pathlib import Path


def test_release_manifest_preserves_68_6_guardrails_under_69_0():
    data = json.loads(Path('config/apex_release_manifest.json').read_text())
    assert data['apex_version'] == '69.0.1'
    assert data['build_name'] == 'Unified Historical Evidence Lifecycle Closure'
    g = data['guardrails']
    assert g['abstention_counterfactuals_excluded_from_calibration_grades'] is True
    assert g['effectiveness_findings_auto_promote_policy'] is False
    assert g['decision_outcome_attribution_changes_execution_authority'] is False


def test_capability_registry_declares_effectiveness_surface():
    text = Path('config/apex_capability_registry.yaml').read_text()
    assert 'apex_version: 69.0.1' in text
    assert 'decision_outcome_attribution:' in text
    assert '/api/effectiveness/abstentions' in text
    assert 'abstention_counterfactuals_do_not_enter_calibration_grading_results' in text
