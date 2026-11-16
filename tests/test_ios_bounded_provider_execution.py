"""No networks, broker actions or market data needed for these tests."""
import threading
import time
from engine import ios_bounded_provider_execution as provider


def _unique(name):
    return f"test-{name}-{time.monotonic_ns()}"


def test_success_result_and_no_persistent_cache():
    key = _unique('ok')
    value, degraded, status = provider.fetch_many([(key, lambda: {'a': 1}, (), {})], timeout=1)
    assert value[key] == {'a': 1}
    assert degraded == []
    assert status[key] == 'COMPLETED'
    assert provider.snapshot()['retained_provider_payloads'] == 0


def test_timeout_retains_slot_until_running_call_finishes():
    key = _unique('slow')
    entered, release = threading.Event(), threading.Event()
    def slow():
        entered.set()
        release.wait(timeout=3)
        return {'ignored': True}
    try:
        value, degraded, status = provider.fetch_many([(key, slow, (), {})], timeout=0.05)
        assert entered.wait(1)
        assert status[key] == 'TIMED_OUT'
        again, degraded2, status2 = provider.fetch_many([(key, lambda: 99, (), -1)], timeout=.05)
        assert again[key] == -1
        assert status2[key] == 'BUSY_SKIPPED'
    finally:
        release.set()
    deadline = time.monotonic() + 2
    while provider.snapshot()['active'] and time.monotonic() < deadline:
        time.sleep(.01)
    assert provider.snapshot()['active'] == 0
    value, degraded, status = provider.fetch_many([(key, lambda: 42, (), None)], timeout=1)
    assert value[key] == 42


def test_six_active_ceiling_and_no_queue():
    entered = [threading.Event() for _ in range(6)]
    release = threading.Event()
    keys = [_unique(f'slot-{i}') for i in range(6)]
    def make_slow(i):
        def slow():
            entered[i].set()
            release.wait(3)
        return slow
    try:
        _, degraded, statuses = provider.fetch_many([(key, make_slow(i), (), []) for i,key in enumerate(keys)], .1)
        assert all(event.wait(1) for event in entered)
        assert all(statuses[key] == 'TIMED_OUT' for key in keys)
        blocked_key = _unique('extra')
        values, _, statuses = provider.fetch_many([(blocked_key, lambda: 'never', (), 'default')], .1)
        assert values[blocked_key] == 'default'
        assert statuses[blocked_key] == 'BUSY_SKIPPED'
        assert provider.snapshot()['active'] <= 6
        assert provider.snapshot()['peak_active'] <= 6
    finally:
        release.set()
    deadline=time.monotonic()+2
    while provider.snapshot()['active'] and time.monotonic() < deadline:
        time.sleep(.01)
    assert provider.snapshot()['active'] == 0


def test_errors_fail_closed_to_defaults():
    key=_unique('error')
    def fail():
        raise RuntimeError('provider offline')
    values, degraded, statuses = provider.fetch_many([(key, fail, (), ['default'])], 1)
    assert values[key] == ['default']
    assert degraded == [key]
    assert statuses[key] == 'PROVIDER_ERROR'


def test_duplicate_key_rejected_before_any_submission():
    key=_unique('duplicate')
    try:
        provider.fetch_many([(key, lambda: 1, (), 0),(key, lambda: 2, (), 0)], 1)
    except ValueError as exc:
        assert 'DUPLICATE_KEY' in str(exc)
    else:
        raise AssertionError('duplicate keys not rejected')


def test_health_snapshot_has_no_authority():
    snapshot=provider.snapshot()
    assert snapshot['maximum_active_calls'] == 6
    assert snapshot['pending_queue_limit'] == 0
    assert snapshot['execution_authority'] is False
    assert snapshot['decision_authority'] is False
