from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_app_registers_workspace_injector():
    source=(ROOT/'app.py').read_text(encoding='utf-8')
    assert '@app.after_request' in source
    assert 'inject_apex41_workspace' in source
    # Cache-bust version is intentionally NOT pinned: it bumps every UI phase
    # (41.0 -> 42.0 -> ...) and a literal pin rots on the next bump. Assert the
    # injector wires BOTH assets with SOME versioned cache-bust instead.
    import re
    assert re.search(r"/static/css/apex_workspace\.css\?v=[\d.]+", source)
    assert re.search(r"/static/js/apex_workspace\.js\?v=[\d.]+", source)

def test_workspace_assets_preserve_phase40_core_features():
    js=(ROOT/'static/js/apex_workspace.js').read_text(encoding='utf-8')
    css=(ROOT/'static/css/apex_workspace.css').read_text(encoding='utf-8')
    for token in ('Ctrl K','ap40:favorites','Find Trade','Execute','Review'):
        assert token in js
    for token in ('.ap41-sidebar','.ap41-topbar','.ap41-overlay','@media(max-width:1024px)'):
        assert token in css

def test_navigation_routes_exist_in_repository():
    js=(ROOT/'static/js/apex_workspace.js').read_text(encoding='utf-8')
    combined='\n'.join(p.read_text(encoding='utf-8',errors='ignore') for p in [ROOT/'app.py',*sorted((ROOT/'engine').glob('*routes.py')),ROOT/'engine/execution/trade_routes.py'])
    routes=sorted(set(part.split("'",1)[0] for part in js.split("','/")[1:]))
    missing=[f'/{route}' for route in routes if f"'/{route}'" not in combined and f'"/{route}"' not in combined]
    assert not missing,missing
