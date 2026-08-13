"""Tests for the /api/institutional_os single-flight compose guard.

Reproduces the thundering-herd that starved the worker threads: on a cold start
(no cached result yet), every concurrent request used to fall through and launch
its own full compose. The guard must let exactly one caller compose and make the
rest return immediately.
"""
import time

import app


def _reset(ticker):
    with app._IOS_CACHE_LOCK:
        app._IOS_CACHE.pop(ticker, None)


def test_first_caller_claims_slot_cold_start():
    t = "ZZTEST1"
    _reset(t)
    # No cache exists yet — the cold-start case. First caller must win.
    assert app._ios_try_begin(t) is True


def test_second_concurrent_caller_is_rejected():
    t = "ZZTEST2"
    _reset(t)
    assert app._ios_try_begin(t) is True    # first claims
    assert app._ios_try_begin(t) is False   # second must NOT compose
    assert app._ios_try_begin(t) is False   # and neither does a third


def test_slot_released_allows_next_compose():
    t = "ZZTEST3"
    _reset(t)
    assert app._ios_try_begin(t) is True
    app._ios_mark_in_progress(t, False)     # compose finished
    assert app._ios_try_begin(t) is True     # next compose may proceed


def test_leaked_slot_self_heals_after_timeout():
    t = "ZZTEST4"
    _reset(t)
    assert app._ios_try_begin(t) is True
    # Simulate a leaked in-progress flag from a stalled/crashed compose.
    with app._IOS_CACHE_LOCK:
        app._IOS_CACHE[t]["inflight_since"] = time.monotonic() - (app._IOS_MAX_INFLIGHT + 5)
    # A caller after the max-inflight window reclaims the slot instead of
    # being frozen out forever.
    assert app._ios_try_begin(t) is True


def test_within_window_still_blocks():
    t = "ZZTEST5"
    _reset(t)
    assert app._ios_try_begin(t) is True
    with app._IOS_CACHE_LOCK:
        app._IOS_CACHE[t]["inflight_since"] = time.monotonic() - 1  # recent
    assert app._ios_try_begin(t) is False


def test_endpoint_returns_fast_when_compose_in_flight():
    """With a compose already in flight, the endpoint must return immediately
    with refresh_in_progress instead of launching another compose."""
    t = "ZZTESTAPI"
    _reset(t)
    # Mark a compose in flight for this ticker.
    with app._IOS_CACHE_LOCK:
        app._IOS_CACHE[t] = {"data": {"cached": "value"}, "ts": time.monotonic(),
                             "in_progress": True, "inflight_since": time.monotonic()}
    client = app.app.test_client()
    start = time.monotonic()
    resp = client.get(f"/api/institutional_os?ticker={t}")
    elapsed = time.monotonic() - start
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get("status") == "refresh_in_progress"
    # 47.0.7 status truth: a FRESH cache being refreshed is not stale — the
    # payload is served with honest cache-age metadata instead of a blanket
    # stale flag. (The pre-47.0.7 contract asserted stale=True here.)
    assert body.get("stale") is False
    assert body.get("cache_age_seconds") is not None
    assert body.get("cached") == "value"  # served the cached payload, no recompose
    # Fast path: must not have run the multi-second compose.
    assert elapsed < 2.0
    _reset(t)


def test_endpoint_cold_start_no_cache_returns_warming_up():
    """Cold start with no cache but a compose already claimed elsewhere: the
    concurrent caller gets a warming-up payload, not a second compose."""
    t = "ZZTESTCOLD"
    _reset(t)
    with app._IOS_CACHE_LOCK:
        app._IOS_CACHE[t] = {"data": None, "ts": 0.0, "in_progress": True,
                             "inflight_since": time.monotonic()}
    client = app.app.test_client()
    start = time.monotonic()
    resp = client.get(f"/api/institutional_os?ticker={t}")
    elapsed = time.monotonic() - start
    assert resp.status_code == 200
    body = resp.get_json()
    # 47.0.7 status truth: cold start with NO data yet reports "warming"
    # (distinct from "refresh_in_progress", which means cached data exists and
    # is being refreshed). refresh_in_progress=True still signals the compose.
    assert body.get("status") == "warming"
    assert body.get("refresh_in_progress") is True
    assert body.get("stale") is True
    assert elapsed < 2.0
    _reset(t)
