from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_app_registers_workspace_injector():
    source = (ROOT / 'app.py').read_text(encoding='utf-8')
    assert '@app.after_request' in source
    assert 'inject_apex40_workspace' in source
    assert '/static/css/apex_workspace.css?v=40.0' in source
    assert '/static/js/apex_workspace.js?v=40.0' in source


def test_workspace_assets_define_core_features():
    js = (ROOT / 'static/js/apex_workspace.js').read_text(encoding='utf-8')
    css = (ROOT / 'static/css/apex_workspace.css').read_text(encoding='utf-8')
    for token in ('Ctrl K', 'ap40:favorites', 'Find Trade', 'Execute', 'Review'):
        assert token in js
    for token in ('.ap40-sidebar', '.ap40-topbar', '.ap40-overlay', '@media(max-width:900px)'):
        assert token in css


def test_navigation_routes_exist_in_repository():
    js = (ROOT / 'static/js/apex_workspace.js').read_text(encoding='utf-8')
    combined = '\n'.join(p.read_text(encoding='utf-8', errors='ignore') for p in [ROOT/'app.py', *sorted((ROOT/'engine').glob('*routes.py')), ROOT/'engine/execution/trade_routes.py'])
    routes = sorted(set(part.split("'", 1)[0] for part in js.split("','/")[1:]))
    missing = [f'/{route}' for route in routes if f"'/{route}'" not in combined and f'"/{route}"' not in combined]
    assert not missing, missing
