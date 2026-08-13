from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'app.py').read_text(encoding='utf-8')
ROADMAP = (ROOT / 'engine' / 'institutional_roadmap_routes.py').read_text(encoding='utf-8')


def test_apex65_monday_critical_endpoints_fail_soft():
    for component in ('market_memory', 'cross_asset_intelligence', 'strategy_orchestration'):
        assert f'"component": "{component}"' in APP
    assert APP.count('"error_code": "BUILD_FAILED"') >= 3
    assert APP.count('"fallback_used": bool(') >= 3


def test_phase31_evidence_status_is_canonical():
    assert '@app.route("/api/evidence/status", methods=["GET"])' in APP
    assert "@app.get('/api/evidence/legacy/status')" in ROADMAP
    assert "@app.get('/api/evidence/status')" not in ROADMAP


def test_legacy_command_center_stays_deleted_after_consolidation():
    assert not (ROOT / 'engine' / 'institutional_command_center_v245_routes.py').exists()
    assert not (ROOT / 'engine' / 'institutional_command_center_v245.py').exists()


def test_request_observability_installed():
    assert 'X-APEX-Request-ID' in APP
    assert 'X-APEX-Duration-Ms' in APP
    assert 'def apex65_request_context' in APP


def test_runtime_route_audit_installed():
    assert '@app.get("/api/runtime/route-audit")' in APP
    assert 'duplicate_route_count' in APP
    assert 'critical_missing' in APP


def test_contract_audit_script_parses():
    path = ROOT / 'tools' / 'apex65_contract_audit.py'
    ast.parse(path.read_text(encoding='utf-8'))


def test_apex6501_legacy_roadmap_does_not_re_register_canonical_runtime_routes():
    from pathlib import Path
    text = Path('engine/institutional_roadmap_routes.py').read_text(encoding='utf-8')
    assert "@app.get('/api/execution-intelligence/status')" not in text
    assert "@app.get('/api/trade-management/status')" not in text
    assert "@app.post('/api/trade-management/evaluate')" not in text
    # Unique legacy persistence / analysis surfaces are intentionally retained.
    assert "@app.post('/api/trade-management/record')" in text
    assert "@app.get('/api/trade-management/history')" in text
    assert "@app.post('/api/execution-intelligence/evaluate')" in text
