from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def test_release_truth_69_3_2():
    manifest = json.loads((ROOT / 'config/apex_release_manifest.json').read_text())
    assert tuple(map(int, manifest['apex_version'].split('.'))) >= (69, 3, 2)
    assert manifest['guardrails']['changes_trade_decisions'] is False
    assert manifest['guardrails']['changes_trade_decisions'] is False
    assert manifest['guardrails']['changes_execution_authority'] is False
    assert manifest['guardrails']['premium_discipline_fail_soft_read_model'] is True


def test_premium_command_center_is_fail_soft_and_json_safe():
    source = (ROOT / 'engine/premium_discipline_routes.py').read_text()
    assert 'def _safe_advisory_section' in source
    assert 'def _json_safe' in source
    assert 'payload["component_diagnostics"] = diagnostics' in source
    assert 'payload["degraded"] = bool(diagnostics)' in source
    assert 'return jsonify(_json_safe(' in source


def test_all_components_does_not_coerce_structured_bullets_to_object_object():
    source = (ROOT / 'static/js/apex_all_components.js').read_text()
    assert "typeof x==='string'?x:" in source
    assert "x.text||x.summary||x.reason||x.label||x.title" in source
    assert '/api/mission_control</span>' not in (ROOT / 'templates/apex_all_components.html').read_text()


def test_operator_dashboards_hide_raw_json_by_default():
    similarity = (ROOT / 'templates/institutional_similarity_lab.html').read_text()
    readiness = (ROOT / 'templates/historical_readiness_dashboard.html').read_text()
    assert 'Technical details' in similarity
    assert 'Feature count' in similarity
    assert 'Readiness Gates' in readiness
    assert 'gateRows' in readiness
    assert 'unlockRows' in readiness
    assert '<pre id="gates">' not in readiness


def test_premium_ui_uses_partial_unavailable_states_without_alert():
    source = (ROOT / 'templates/premium_discipline_command_center.html').read_text()
    assert "c.degraded?'PARTIAL'" in source
    assert 'Premium Discipline data unavailable.' in source
    assert 'alert(e.message)' not in source
