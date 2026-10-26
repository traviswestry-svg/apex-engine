# APEX 69.10.46 — Runtime Memory & Scheduler Accounting Stabilization

## Production symptom
Previous 69.10.45 production status reported 27,519,914 freshness-budget exhausted cycles versus 1,218 scan completions, with 94.99% raw cgroup memory usage and no confirmed OOM or PSI stall.

## Verified root risk and correction
In `app.scanner_loop`, when `_age >= _stale`, the deadline plan may return `_sleep == 0`, resulting in an unbounded no-backoff loop and a rapidly inflating per-loop freshness exhaustion counter. The patch adds a minimum five-second sleep *only when the freshness budget is exhausted*, without overriding `SCAN_LOCK`, dispatching orders, or changing healthy scheduler cadence.

The existing cumulative `freshness_budget_exhausted_cycles` remains for compatibility. New `scheduler_cycles_accounted`, `freshness_budget_exhausted_episodes`, `freshness_budget_exhausted_active` and `last_freshness_exhausted_episode_at` provide differentiated context. All new counters are process-local, resetting on restart; they do not rewrite historical evidence.

## Memory
`memory_pressure_status` now reports a bounded process-local `bounded_trend` of at most 16 cgroup samples, sampled no more often than once per minute. It tracks the delta in estimated non-inactive-file bytes while explicitly marking `leak_confirmed=false`; raw usage can include reclaimable file cache. No forced garbage collection, deletion, SQLite cache mutation, or unsafe memory reclamation.

## Validation
- New scheduler/memory tests + existing scanner and runtime-memory tests: 13 passed.
- Selected gamma/scanner/settlement regression tests: 16 passed.
- Python compilation: passed.
- Full repository CI: NOT run/certified in this environment. GitHub CI is required before production deployment.

## Deployment checklist
1. Apply changed files on a branch created from current main; resolve any modifications made after 69.10.45 before merge.
2. Run full CI/release and configuration governance checks, plus gamma-transition regression suite.
3. Deploy to Render, confirm version 69.10.46. Note that process-local counters reset on restart.
4. Inspect `scan_completion_runtime` for reasonable `scheduler_cycles_accounted`, `freshness_budget_exhausted_cycles`, `freshness_budget_exhausted_episodes`, and `last_scheduler_sleep_seconds`; compare with scan attempts over an hour.
5. Inspect `memory_pressure.bounded_trend` after 15+ minutes; don't call a memory leak based on a single reading.
6. Keep decision and execution authority disabled; no paper-order enablement is contained in this release.
