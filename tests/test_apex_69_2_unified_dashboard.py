from pathlib import Path
import json


def test_unified_dashboard_route_and_template_exist():
    app = Path('app.py').read_text()
    assert '@app.route("/apex_os/all")' in app
    assert '@app.route("/apex_dashboard")' in app
    assert 'apex_all_components.html' in app
    assert Path('templates/apex_all_components.html').exists()
    assert Path('static/css/apex_all_components.css').exists()
    assert Path('static/js/apex_all_components.js').exists()


def test_all_requested_components_are_visible_without_navigation_click():
    text = Path('templates/apex_all_components.html').read_text()
    for label in ['Mission Control','Execution','Analysis','Chart','Flow','Story','Levels','Tape','Replay','Signal Log']:
        assert f'>{label}<' in text


def test_existing_top_navigation_is_present():
    text = Path('templates/apex_all_components.html').read_text()
    for label in ['APEX','Scanner','Terminal','Assistant','Flow / GEX','Trade Command','Operations','Execution OS','Morning Readiness','Status','Health']:
        assert f'>{label}<' in text


def test_apex_os_exposes_all_components_at_top():
    text = Path('templates/apex_os.html').read_text()
    assert '<a href="/apex_os/all" class="nav-all-components">All Components</a>' in text


def test_dashboard_is_read_only_composition():
    js = Path('static/js/apex_all_components.js').read_text()
    assert "fetch(url,{cache:'no-store'})" in js
    assert "method:'POST'" not in js
    manifest = json.loads(Path('config/apex_release_manifest.json').read_text())
    assert manifest['apex_version'] == '69.2.0'
    assert manifest['guardrails']['unified_dashboard_read_only'] is True
    assert manifest['guardrails']['dashboard_changes_decision_authority'] is False
