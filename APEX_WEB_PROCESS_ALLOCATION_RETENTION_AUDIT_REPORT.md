# APEX Web-Process Anonymous-Memory Allocation & Retention Audit — Candidate

**Baseline:** `apex-engine-main(20261112-221036).zip` (November 12 source). This is a version-neutral, observational extension to APEX 69.10.47; not yet integrated or deployed.

## Problem motivating the audit

The supplied November 13 health response observed approximately +214,896,640 bytes of cgroup anonymous memory and +158,724 KiB of web RSS across a 1,460.7-second observation window. No new limit events occurred within the most recent web-worker-local pair, but historical cumulative limit events stood at 837. This does not establish a leak or isolate allocation ownership.

## Scope and implementation

Adds `engine/web_process_allocation_retention_audit.py` and a fail-open `/health` hook. The hook uses bounded read-only `/proc/self/status`, `/proc/self/smaps_rollup`, `/proc/self/stat`, and cgroup `memory.stat`/`memory.current` reads. Collects web RSS, anonymous RSS, process private dirty/clean, PSS anon when supported, VmData, Threads, Python `sys.getallocatedblocks()`, and `gc.get_count()` (without invoking collection). It retains **16 scalar snapshots** in a bounded process-local deque; samples are at least 30 seconds apart. Same-PID/different-start-ticks points are never compared. No requests, response bodies, process trees, objects, allocations traces, or database rows are retained.

Output is `web_process_allocation_retention_audit` in `/health`, with `process_identity`, `latest_process`, `latest_cgroup`, `history_samples`, `oldest_to_current`, and explicit limits. There is no statistical ownership inference from these snapshots. The added block is within existing health payload construction and existing response serialization attribution captures its minimal overhead.

## Safeguards

No GC collection, tracemalloc, SQLite reads, arbitrary process enumeration, memory reclaim, scheduler changes, broker changes, execution eligibility changes, env vars, or evidence modifications. Failure of the optional sampler yields `DIAGNOSTIC_UNAVAILABLE`, not an endpoint failure. Existing single-worker capped-request Gunicorn recycling remains unchanged.

## Validation

- **104 passed** in the combined selected tests, including new audit checks, existing health/memory diagnostics, gamma transition/integrity, canonical settlement eligibility, release truth, and consolidation guard.
- New tests: process identity / PID reuse, nonmonotonic clock, bounded history, process restart, proc-stat parsing with whitespace, missing `/proc`, and static route wiring.
- Python compilation passed and direct local `/proc` sampling returned verified PID/start ticks and private-memory metrics.
- **Full CI has NOT been certified**: Flask is not installed in the local environment, so app-level runtime import and the entire test suite cannot be verified here. Run CI in the standard dependencies-installed GitHub environment.

## Interpretation and next step

Compare several `/health` observations from the **same web worker and same cgroup**. Sustained growth in anonymous RSS, private dirty, and allocated blocks could justify a separate opt-in, bounded profiler; stable or declining values weaken a retention hypothesis. Block counts are not bytes, and even simultaneous growth is not proof of a leak. If concurrent endpoints or allocator caches affect results, request-level allocation ownership remains unresolved.

**Stage 3 SQLite storage optimization stays on hold.**
