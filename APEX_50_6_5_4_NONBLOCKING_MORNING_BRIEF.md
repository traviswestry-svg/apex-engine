# APEX 50.6.5.4 — Non-Blocking Morning Brief Response Fix

## Objective
Eliminate the Morning Readiness UI hang introduced by the asynchronous Anthropic pipeline by removing narrative job-store access and worker scheduling from the synchronous `/api/morning-brief` request path.

## Root cause
50.6.5.3 moved Anthropic HTTP work to a background worker, but `generate_morning_brief()` still accessed the persisted narrative job store and called the scheduler before the deterministic Morning Brief response completed. The scheduler performs SQLite work and launches the worker, leaving persistence/scheduling contention inside the HTTP request lifecycle.

## Repair
- Added `defer_async_enqueue=True` to the Morning Brief orchestration path used by `/api/morning-brief`.
- In deferred mode, `generate_morning_brief()` performs no async narrative DB read, DB write, scheduler call, or Anthropic network call.
- The generator returns an internal async request descriptor that is removed before JSON serialization.
- After deterministic payload assembly and official forecast archive persistence, `app.py` calls `enqueue_nonblocking()`.
- `enqueue_nonblocking()` starts a launcher thread and returns immediately without SQLite or network I/O on the HTTP request thread.
- Frontend polling may briefly observe `NOT_FOUND` before the launcher persists `PENDING`; existing polling already tolerates this state.

## Timing telemetry
The Morning Brief response now contains `response_timing` with:
- `providers_ms`
- `deterministic_generation_ms`
- `archive_ms`
- `async_enqueue_ms`
- `response_ready_ms`
- `anthropic_waited_inline: false`

`operational_status.latency_ms` is updated at the actual response-ready boundary.

## Safety / compatibility
- Deterministic levels, LTPE path, data quality, official forecast archive, risk logic, signal logic, and broker execution are unchanged.
- Existing direct `async_narrative=True` behavior remains backward compatible unless `defer_async_enqueue=True` is explicitly used.
- The asynchronous Anthropic worker retains the adaptive retry, pause-turn handling, telemetry, and circuit-breaker logic from 50.6.5.2/50.6.5.3.

## Validation
- 53/53 targeted APEX 50.6 + Monday-readiness regressions PASS.
- Nonblocking enqueue timing regression PASS.
- Inline narrative-store isolation regression PASS.
- Route ordering regression PASS.
- Repository Python compilation PASS.
