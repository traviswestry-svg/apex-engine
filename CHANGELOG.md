# /api/institutional_os Single-Flight Hotfix

## Problem (from your DevTools capture)
Console: `/api/institutional_os timed out after 6s` looping; Network: all API
calls (pending)/(canceled) at 0 kB. The endpoint composes the full nine-engine
pipeline live per request (6 parallel provider fetches). Its single-flight guard
only returned early when a cached result already existed:
    if cached is not None and _IOS_CACHE[ticker]['in_progress']: return cached
On a cold start (pre-market, nothing cached yet) cached is None, so every retry
fell through and launched its own compose — a thundering herd that saturated the
gunicorn worker (1 worker x 4 threads). One slow endpoint starved the whole
dashboard.

## Fix
- New `_ios_try_begin(ticker)`: atomic check-and-set single-flight claim under
  the existing `_IOS_CACHE_LOCK`. Exactly one caller composes; concurrent callers
  return stale cache (or a fast 'refresh_in_progress' warming-up payload)
  immediately — including the cold-start no-cache case that was the actual bug.
- Self-healing: a slot held > 30s (leaked/stalled compose) is reclaimed, so the
  endpoint can never freeze permanently on 'refresh_in_progress'.
- Closed a flag-leak path in the apex_engines-unavailable fallback.

## Verified
- 7 new tests pass (cold-start claim, concurrent rejection, slot release,
  self-heal reclaim, in-window block, and the endpoint returning in <2s with
  refresh_in_progress instead of composing).
- Full suite: 1306 passed, 1 deselected (pre-existing unrelated refusal_replay).
- No new env vars; the timeout is a constant (no governance/env-drift impact).

## Not a full re-architecture
This stops the starvation. The deeper improvement (move the compose to the
background scanner and have the endpoint only ever SERVE cache) is a larger
change worth doing later; this hotfix is the surgical, low-risk piece.
