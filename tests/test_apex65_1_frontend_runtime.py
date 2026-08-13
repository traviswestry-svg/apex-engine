from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_shared_api_client_exists_and_has_required_contract():
    text = (ROOT / 'static/js/apex_api.js').read_text()
    for token in ['X-APEX-Request-ID', 'X-APEX-Duration-Ms', 'STALE', 'DEGRADED', 'UNAVAILABLE', 'FAILED', 'apex:api-result', 'ApexAPI']:
        assert token in text


def test_trade_director_loads_shared_client_before_requests():
    text = (ROOT / 'templates/assistant.html').read_text()
    assert "filename='js/apex_api.js'" in text
    assert 'ApexAPI.get' in text
    assert 'apexApiRequestId' in text
    assert text.index("filename='js/apex_api.js'") < text.index('async function loadDirector()')


def test_institutional_os_loads_shared_client():
    text = (ROOT / 'templates/apex_os.html').read_text()
    assert "filename='js/apex_api.js'" in text
    assert text.index("filename='js/apex_api.js'") < text.index("filename='js/apex_os.js'")
