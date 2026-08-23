import json
from pathlib import Path


def test_release_manifest_preserves_68_6_guardrails_under_69_0():
    data = json.loads(Path('config/apex_release_manifest.json').read_text())
    assert tuple(map(int, data['apex_version'].split('.'))) >= (69, 0, 1)
    # Build names may advance in later 69.x releases; the historical 68.6
    # contract is the preserved guardrail set below, not a patch-name allowlist.
    assert isinstance(data.get('build_name'), str) and data['build_name'].strip()
    g = data['guardrails']
    assert g['abstention_counterfactuals_excluded_from_calibration_grades'] is True
    assert g['effectiveness_findings_auto_promote_policy'] is False
    assert g['decision_outcome_attribution_changes_execution_authority'] is False


def test_capability_registry_declares_effectiveness_surface():
    text = Path('config/apex_capability_registry.yaml').read_text()
    assert 'apex_version: 69.' in text
    assert 'decision_outcome_attribution:' in text
    assert '/api/effectiveness/abstentions' in text
    assert 'abstention_counterfactuals_do_not_enter_calibration_grading_results' in text
