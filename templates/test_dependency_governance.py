import json
import logging
import pytest
from engine import dependency_governance as dg

@pytest.fixture(autouse=True)
def clean():
    dg.reset_runtime_state(); yield; dg.reset_runtime_state()

def test_inventory_is_authoritative_and_secret_free():
    payload=dg.inventory(); assert payload['count'] >= 8
    raw=json.dumps(payload)
    assert 'secret_values' not in raw.lower()

def test_missing_optional_dependencies_warn_not_block():
    x=dg.diagnostics({})
    assert x['state'] == 'WARNING' and x['ok'] is True

def test_observation_and_latency_are_reported():
    dg.record_observation('polygon_massive', ok=True, latency_ms=12.3456)
    svc=next(x for x in dg.diagnostics({'POLYGON_API_KEY':'super-secret'})['services'] if x['name']=='polygon_massive')
    assert svc['state']=='HEALTHY' and svc['last_observation']['latency_ms']==12.346
    assert 'super-secret' not in json.dumps(svc)

def test_failures_open_circuit_and_reject_calls():
    def bad(): raise ValueError('credential-should-not-leak')
    for _ in range(4):
        with pytest.raises(ValueError): dg.governed_call('polygon_massive', bad)
    assert dg.circuit_state('polygon_massive')['state']=='OPEN'
    with pytest.raises(RuntimeError): dg.governed_call('polygon_massive', lambda: 1)
    assert 'credential-should-not-leak' not in json.dumps(dg.diagnostics({}))

def test_success_closes_breaker():
    assert dg.governed_call('database', lambda: 7)==7
    assert dg.circuit_state('database')['state']=='CLOSED'

def test_timeout_invalid_value_falls_back():
    svc=next(x for x in dg.diagnostics({'SOURCE_TIMEOUT_SECONDS':'bad','POLYGON_API_KEY':'x'})['services'] if x['name']=='polygon_massive')
    assert svc['timeout_seconds']==8.0

def test_dependency_endpoints_200():
    import app as app_module
    client=app_module.app.test_client()
    for route in ('/api/dependencies/status','/api/dependencies/diagnostics','/api/dependencies/inventory'):
        r=client.get(route); assert r.status_code==200; assert r.get_json()['ok'] is True

def test_mission_control_renders_dependency_panel():
    import app as app_module
    r=app_module.app.test_client().get('/apex_os')
    assert r.status_code==200 and b'DEPENDENCY HEALTH' in r.data
