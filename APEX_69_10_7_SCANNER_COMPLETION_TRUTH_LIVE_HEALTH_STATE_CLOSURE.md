# APEX 69.10.7 — Scanner Completion Truth & Live Health State Closure

## Production finding
APEX 69.10.6 proved the replay-frame → feature persistence → canonical excursion-capture path live in production. During the same session, `/health` remained `STALE` because the last completed full-scan timestamp stopped advancing while the dedicated scanner heartbeat and scanner-owned learning pipeline continued to advance.

That condition must not be normalized as healthy: a fresh process heartbeat proves process liveness, not successful full-scan completion.

## Closure
69.10.7 separates full-scan completion truth from heartbeat/background activity and publishes explicit scanner-process completion telemetry:
- scan attempts
- completed scans
- failures
- scheduler lock skips
- bounded lock-contention retries
- last attempt/completion/failure timestamps
- last completed duration/result

The dedicated scanner heartbeat now carries this explicit completion record. When that heartbeat is fresh, `/health` and `/api/runtime/health` prefer the scanner-process `last_completed_at` and duration over ambiguous web-process local state.

If the heartbeat is fresh but the full-scan completion is stale, health remains fail-closed as `STALE` with scanner state `FULL_SCAN_STALLED`. Background flow-learning, grading, or HLCE activity never substitutes for a completed full scan.

A transient non-blocking scan-lock collision receives one short bounded retry before the normal scanner cadence. The lock is never bypassed and concurrent scans are never permitted.

## Preserved guardrails
- `HEALTH_STALE_AFTER_S` unchanged.
- Fresh heartbeat cannot mask stale full-scan completion.
- No trade-decision changes.
- No behavioral authority.
- No execution authority.
- No replay-frame, flow-feature, excursion, calibration, grading, or broker changes.
- No synthetic evidence or historical rewrite.

## Live verification contract
During MARKET_OPEN verify:
1. scanner heartbeat remains fresh;
2. `scan_completion_runtime.scan_attempts` increases;
3. `scan_completion_runtime.scan_completed` increases as full scans finish;
4. `last_completed_at` advances on every successful full scan;
5. `/health.last_scan_at` matches authoritative scanner-process completion truth;
6. `HEALTHY` is returned only while the full-scan timestamp is inside the existing freshness window;
7. if completions stall while heartbeat remains fresh, health reports `STALE` / `FULL_SCAN_STALLED` with lock/failure diagnostics rather than falsely reporting healthy.
