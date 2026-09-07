# /api/institutional_os single-flight fix — manual patch (3 edits)

Apply these to your running app.py if you are NOT on the full-stack app.py in
this zip. All three are in/near the institutional_os endpoint.

## EDIT 1 — add the self-healing single-flight helper
Right AFTER the `_ios_mark_in_progress(...)` function, add:

    # Max time a single compose may hold the single-flight slot before it is
    # treated as stale and reclaimed (guards a leaked in-progress flag).
    _IOS_MAX_INFLIGHT = 30.0


    def _ios_try_begin(ticker: str) -> bool:
        """Atomically claim the single-flight compose slot for `ticker`.
        True -> this caller runs the compose. False -> one is already in flight
        (return cached/warming-up instead). A slot held longer than
        _IOS_MAX_INFLIGHT seconds is reclaimed so a leaked flag self-heals."""
        with _IOS_CACHE_LOCK:
            entry = _IOS_CACHE.get(ticker)
            now = time.monotonic()
            if entry and entry.get("in_progress"):
                started = entry.get("inflight_since", 0.0)
                if (now - started) < _IOS_MAX_INFLIGHT:
                    return False
            if entry is None:
                _IOS_CACHE[ticker] = {"data": None, "ts": 0.0, "in_progress": True,
                                      "inflight_since": now}
            else:
                entry["in_progress"] = True
                entry["inflight_since"] = now
            return True

## EDIT 2 — replace the guard block in api_institutional_os()
REPLACE:

    # ── Return cached data immediately if a refresh is already running ──────
    if not force:
        cached = _ios_cached(ticker)
        if cached is not None and _IOS_CACHE.get(ticker, {}).get("in_progress"):
            payload = dict(cached)
            payload.update({"stale": True, "status": "refresh_in_progress",
                             "response_ms": round((time.monotonic()-t_start)*1000, 1)})
            return jsonify(payload)

    _ios_mark_in_progress(ticker, True)

WITH:

    # ── Single-flight: at most one compose per ticker at a time. Concurrent
    #    callers — including the cold-start case with no cache yet — return
    #    immediately instead of piling on and starving the worker threads. ─────
    if not force:
        if not _ios_try_begin(ticker):
            cached = _ios_cached(ticker)
            payload = dict(cached) if cached is not None else {
                "ok": True, "ticker": ticker,
                "interpretation": "Composing institutional OS — first result not ready yet.",
            }
            payload.update({"stale": True, "status": "refresh_in_progress",
                            "response_ms": round((time.monotonic() - t_start) * 1000, 1)})
            return jsonify(payload)
    else:
        _ios_mark_in_progress(ticker, True)

## EDIT 3 — release the slot in the apex_engines-unavailable fallback
Find the tail fallback:

    # apex_engines.py not available — use 4.5 build_institutional_os
    try:
        data = build_institutional_os(ticker, include_heatmap=include_heatmap)

Insert a release line so a leaked flag can't freeze this path:

    # apex_engines.py not available — use 4.5 build_institutional_os
    _ios_mark_in_progress(ticker, False)  # release single-flight slot
    try:
        data = build_institutional_os(ticker, include_heatmap=include_heatmap)
