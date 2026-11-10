import json
from pathlib import Path
from types import SimpleNamespace
from engine import health_response_memory_attribution as h


def setup_function():
    with h._LOCK:
        h._EVENTS.clear()


def test_first_response_does_not_claim_same_request_measurement():
    first = h.prior_completed()
    assert first['status'] == 'NO_PRIOR_COMPLETED_REQUEST'
    assert first['last_completed'] is None
    assert first['reporting_lag'] == 'COMPLETED_REQUEST_VISIBLE_ON_SUBSEQUENT_HEALTH_RESPONSE'


def test_completed_measures_only_existing_response_without_reencoding():
    class Response:
        def __init__(self):
            self.calls = 0
        def calculate_content_length(self):
            self.calls += 1
            return 1048576
    response = Response()
    start = {'pid': 50, 'started_ns': 1_000_000_000, 'rss_before_kib': 300}
    out = h.completed(start, construction_end_ns=1_002_000_000,
                      construction_end_rss_kib=325, response=response,
                      end_ns=1_008_000_000, end_rss_kib=360)
    assert response.calls == 1
    assert out['payload_construction_ms'] == 2
    assert out['jsonify_serialization_ms'] == 6
    assert out['response_bytes'] == 1048576
    assert out['construction_rss_delta_kib'] == 25
    assert out['serialization_rss_delta_kib'] == 35
    assert out['total_rss_delta_kib'] == 60
    assert h.prior_completed()['last_completed'] == out
    assert 'response_body' not in out and 'payload_body' not in out


def test_negative_delta_is_retained_as_released_memory():
    start = {'pid': 1, 'started_ns': 100, 'rss_before_kib': 300}
    out = h.completed(start, construction_end_ns=200, construction_end_rss_kib=290,
                      response=SimpleNamespace(calculate_content_length=lambda: 10),
                      end_ns=300, end_rss_kib=280)
    assert out['total_rss_delta_kib'] == -20


def test_history_bounded_and_no_response_payload_retention():
    response = SimpleNamespace(calculate_content_length=lambda: 100)
    for i in range(20):
        h.completed({'pid': 1, 'started_ns': i, 'rss_before_kib': 10},
                    construction_end_ns=i+1, construction_end_rss_kib=10,
                    response=response, end_ns=i+2, end_rss_kib=10)
    out = h.prior_completed()
    assert out['completed_requests_observed'] == 8
    assert isinstance(out['last_completed']['response_bytes'], int)
    assert len(json.dumps(out)) < 2500
    assert out['execution_authority'] is False
    assert out['db_reads'] is False


def test_app_wiring_static_health_route_only_and_no_double_jsonify():
    src = Path('app.py').read_text()
    route = src.split('@app.route("/health")', 1)[1].split('# APEX 4.5 NEW API ROUTES', 1)[0]
    assert 'health_memory_attribution.begin()' in route
    assert '"runtime_memory_investigation": runtime_memory_investigation()' in route
    assert '"health_response_memory_attribution": health_memory_attribution.prior_completed()' in route
    assert 'health_memory_attribution.completed(' in route
    assert route.count('jsonify(') == 1
    assert 'return _health_response' in route
    assert '"is_tradeable": s_session == "MARKET_OPEN"' in route
