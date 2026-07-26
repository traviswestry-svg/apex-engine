from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_app_registers_phase41_assets():
    source=(ROOT/'app.py').read_text(encoding='utf-8')
    assert 'inject_apex41_workspace' in source
    # Cache-bust version is intentionally NOT pinned: it bumps every UI phase
    # (41.0 -> 42.0 -> ...) and a literal pin rots on the next bump. Assert the
    # injector wires BOTH assets with SOME versioned cache-bust instead.
    import re
    assert re.search(r"/static/css/apex_workspace\.css\?v=[\d.]+", source)
    assert re.search(r"/static/js/apex_workspace\.js\?v=[\d.]+", source)

def test_phase41_adaptive_features_present():
    js=(ROOT/'static/js/apex_workspace.js').read_text(encoding='utf-8')
    css=(ROOT/'static/css/apex_workspace.css').read_text(encoding='utf-8')
    for token in ('deviceKey', 'MOBILE_TABS', 'ap41-bottom', 'ap41-monitor', 'touchstart', 'ap41:'):
        assert token in js
    for token in ('@media(max-width:600px)', '@media(max-width:1024px)', '@media(min-width:1700px)', '.ap41-bottom', '.ap41-sheet', '.ap41-fab'):
        assert token in css

def test_phase41_preserves_navigation_and_governance():
    js=(ROOT/'static/js/apex_workspace.js').read_text(encoding='utf-8')
    assert 'Ctrl K' in js
    assert 'ap40:favorites' in js
    assert "execution:'/apex_os/trade_command'" in js
