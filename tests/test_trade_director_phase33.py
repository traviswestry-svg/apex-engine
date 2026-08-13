from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_phase33_assets_exist():
    assert (ROOT / 'static/css/trader_workflow.css').is_file()
    assert (ROOT / 'static/js/trader_workflow.js').is_file()

def test_apex_os_has_trader_cockpit_and_collapsible_supporting_context():
    html = (ROOT / 'templates/apex_os.html').read_text(encoding='utf-8')
    assert 'id="traderCockpit"' in html
    assert 'Invalidation / Stop' in html
    assert 'Supporting intelligence and system context' in html
    assert 'trader_workflow.js' in html

def test_assistant_removes_phase_labels_from_live_presentation_without_deleting_modules():
    html = (ROOT / 'templates/assistant.html').read_text(encoding='utf-8')
    js = (ROOT / 'static/js/trader_workflow.js').read_text(encoding='utf-8')
    assert 'Trader Workflow:' in html
    assert 'TRADE DIRECTOR PHASE' in html  # underlying modules preserved
    assert 'phase-label-hidden' in js

def test_confirmation_gate_language_is_preserved():
    html = (ROOT / 'templates/apex_os.html').read_text(encoding='utf-8')
    assert 'CONFIRMATION GATED' in html
    assert 'LOCKED' in html
