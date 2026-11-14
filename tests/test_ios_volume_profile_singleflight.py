"""The volume profile timeout must never start overlapping provider workers."""
import threading
import time
from engine import ios_volume_profile_singleflight as vp


def test_timeout_retains_slot_until_actual_provider_completion():
    started = threading.Event()
    release = threading.Event()
    calls = []

    def slow(**kwargs):
        calls.append(kwargs)
        started.set()
        release.wait(timeout=2)
        return {"profile": "complete"}

    try:
        value, state, _ = vp.fetch(slow, timeout=0.025, ticker="SPX")
        assert started.is_set()
        assert state == "TIMED_OUT" and value == {}
        value, state, _ = vp.fetch(slow, timeout=0.025, ticker="SPX")
        assert state == "BUSY" and value == {}
        assert len(calls) == 1
    finally:
        release.set()
    # Avoid timing-based release guesses: wait for the worker to complete.
    for _ in range(100):
        value, state, _ = vp.fetch(lambda **kw: {"ok": True}, timeout=0.2)
        if state == "COMPLETED":
            assert value == {"ok": True}
            break
        time.sleep(0.005)
    else:
        raise AssertionError("slot was never released")


def test_provider_error_releases_slot():
    def broken(**kw):
        raise RuntimeError("provider unavailable")
    value, state, _ = vp.fetch(broken, timeout=0.2)
    assert value == {} and state == "FAILED"
    value, state, _ = vp.fetch(lambda **kw: {"ok": True}, timeout=0.2)
    assert state == "COMPLETED" and value == {"ok": True}


def test_fetch_reports_elapsed_monotonic_time(monkeypatch):
    times = iter((10.0, 10.125))
    monkeypatch.setattr(vp.time, "monotonic", lambda: next(times))
    value, state, elapsed_ms = vp.fetch(lambda **kw: {"ok": True}, timeout=0.2)
    assert value == {"ok": True}
    assert state == "COMPLETED"
    assert elapsed_ms == 125.0


def test_metrics_have_no_payload_retention():
    metrics = vp.snapshot()
    assert metrics["max_active_provider_calls"] == 1
    assert metrics["execution_authority"] is False
    assert not any(isinstance(value, (list, tuple)) for value in metrics.values())
