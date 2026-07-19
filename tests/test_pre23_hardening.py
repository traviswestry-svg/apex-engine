import os
from pathlib import Path

from flask import Flask

from engine.pre23_hardening import immutable_snapshot, persistence_inventory, route_assurance
from engine.pre23_hardening_routes import register_pre23_hardening_routes
from engine.configuration_governance import REGISTRY


def test_registry_contains_audited_missing_variables():
    required = {
        'APEX_EXECUTION_TICK_SIZE','APEX_MARKET_MEMORY_CAPTURE_ENABLED','APEX_MARKET_MEMORY_DB',
        'APEX_MARKET_MEMORY_MIN_SESSIONS','APEX_MARKET_MEMORY_OUTCOME_WRITES_ENABLED',
        'APEX_MAX_TOTAL_OPEN_RISK','APEX_PREMIUM_EXECUTION_ENABLED','PREMIUM_ELIGIBILITY_THRESHOLD',
        'TRADE_LOSS_LOCKOUT_COUNT','TRADE_MAX_DAILY_LOSS','TRADE_MAX_TRADES_PER_DAY',
    }
    assert required <= set(REGISTRY)


def test_snapshot_is_deep_copied_and_content_addressed():
    source = {'decision': {'bias': 'BULLISH'}, 'rows': [1, 2]}
    snap = immutable_snapshot(source)
    source['decision']['bias'] = 'BEARISH'
    assert snap['payload']['decision']['bias'] == 'BULLISH'
    assert len(snap['snapshot_id']) == 24
    assert snap['immutable'] is True


def test_route_assurance_detects_missing_and_then_passes():
    app = Flask(__name__)
    result = route_assurance(app)
    assert result['state'] == 'BLOCKING'
    for idx, route in enumerate(result['critical_routes']):
        app.add_url_rule(route, f'x{idx}', lambda: 'ok')
    assert route_assurance(app)['state'] == 'PASS'


def test_hardening_routes_return_200():
    app = Flask(__name__)
    register_pre23_hardening_routes(app, lambda: {'price': 6000})
    client = app.test_client()
    assert client.get('/api/pre23-hardening/status').status_code == 200
    assert client.get('/api/pre23-hardening/routes').status_code == 200
    assert client.get('/api/pre23-hardening/persistence').status_code == 200
    assert client.get('/api/institutional-snapshot/status').status_code == 200


def test_persistence_inventory_never_exposes_secret_values(monkeypatch):
    monkeypatch.setenv('TV_WEBHOOK_SECRET', 'never-print-this-value')
    payload = persistence_inventory()
    assert 'never-print-this-value' not in str(payload)


def test_application_factory_returns_registered_flask_app(monkeypatch):
    monkeypatch.setenv('RUN_SCANNER_ON_IMPORT', 'false')
    monkeypatch.setenv('DISABLE_BACKGROUND_SCANNER', 'true')
    from engine.application_composition import create_app, route_inventory
    app = create_app()
    inventory = route_inventory(app)
    assert inventory['count'] > 500
    assert any(row['rule'] == '/health' for row in inventory['routes'])


def test_registry_has_no_production_env_drift():
    import re
    from pathlib import Path
    pattern = re.compile(r'(?:os\.getenv|os\.environ\.get)\(\s*[\"\']([A-Z][A-Z0-9_]*)')
    root = Path(__file__).resolve().parents[1]
    used = set()
    for path in [root / 'app.py', *(root / 'engine').rglob('*.py')]:
        used.update(pattern.findall(path.read_text(encoding='utf-8', errors='ignore')))
    assert not sorted(used - set(REGISTRY))
