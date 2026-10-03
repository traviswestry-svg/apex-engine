import importlib
import sys
import types


def _install_flask_stub():
    if 'flask' in sys.modules:
        return
    flask = types.ModuleType('flask')
    flask.jsonify = lambda *a, **k: None
    flask.render_template = lambda *a, **k: None
    flask.request = types.SimpleNamespace(args={})
    sys.modules['flask'] = flask



def test_readiness_checks_closed_skip_ledger_and_nested_http(monkeypatch):
    _install_flask_stub()
    import engine.operations_routes as ops

    class Rule:
        def __init__(self, rule): self.rule = rule
    class Map:
        def iter_rules(self):
            return iter([Rule('/api/market_health'), Rule('/api/market_status'), Rule('/api/broker/etrade/status'), Rule('/api/trade/spx/preview-entry'), Rule('/api/system/metrics')])
    class App:
        url_map = Map()
        def test_client(self):
            raise AssertionError('readiness must not issue nested Flask requests')

    monkeypatch.setattr(ops, '_database_check', lambda: ops._check('PASS', 'db'))
    monkeypatch.setattr(ops, '_recommendation_ledger_check', lambda: (_ for _ in ()).throw(AssertionError('closed session must not query ledger')))
    checks = ops._readiness_checks(App(), market_open=False)
    assert checks['recommendation_ledger']['status'] == 'BLOCKED'
    assert checks['version_consistency']['details']['probe_mode'] == 'DIRECT_MANIFEST_NO_NESTED_HTTP'


def test_readiness_checks_live_preserve_ledger_evidence(monkeypatch):
    _install_flask_stub()
    import engine.operations_routes as ops
    class Rule:
        def __init__(self, rule): self.rule = rule
    class Map:
        def iter_rules(self): return iter([])
    class App: url_map = Map()
    monkeypatch.setattr(ops, '_database_check', lambda: ops._check('PASS', 'db'))
    monkeypatch.setattr(ops, '_recommendation_ledger_check', lambda: ops._check('PASS', 'ledger-live'))
    checks = ops._readiness_checks(App(), market_open=True)
    assert checks['recommendation_ledger']['status'] == 'PASS'
    assert checks['recommendation_ledger']['summary'] == 'ledger-live'


def test_readiness_archive_hash_ignores_generated_at(tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_GOVERNANCE_DB', str(tmp_path/'gov.db'))
    import engine.report_archive as ra
    ra = importlib.reload(ra)
    base={'score':92,'trading_mode':'ANALYSIS_ONLY','session_date':'2026-10-05','recommendation':'ANALYSIS ONLY'}
    a=ra.archive_readiness({**base,'generated_at':'2026-10-03T12:00:00+00:00'})
    b=ra.archive_readiness({**base,'generated_at':'2026-10-03T12:00:30+00:00'})
    assert a['saved'] is True
    assert b['saved'] is False
    assert b['revision_count'] == 1


def test_evening_recap_ui_surfaces_status_and_provenance_reason():
    text=open('templates/execution_os.html', encoding='utf-8').read()
    assert "j.error||j.status||'failed'" in text
    assert "j.provenance&&j.provenance.reason" in text
