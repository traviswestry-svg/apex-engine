# APEX 69.10.38 — Runtime Observability & Memory Pressure Classification Closure

**Candidate patch; not deployed.** This is intentionally separate from the existing **69.10.38 Settlement Eligibility** candidate. Reconcile the release number before promotion. It is a *source patch*, not a full repository release.

## Files
- `engine/scanner_runtime_truth.py`: adds explicit heartbeat freshness/fallback reason, preserves prior resolver contract.
- `engine/runtime_memory_pressure.py`: read-only cgroup v2 memory summary, including raw usage, inactive-file-adjusted heuristic, PSI, cumulative OOM counters.
- `apply_patch.py`: checks for exact expected `app.py` fragments, aborts on source drift, creates backups, then applies targeted changes.
- `tests/test_runtime_observability_691038.py`: six unit tests.

## Apply to a clean checkout of the CURRENT production repository

```bash
python /path/to/patch/apply_patch.py --repo /path/to/apex-engine-main
cd /path/to/apex-engine-main
python -m pytest -q /path/to/patch/tests/test_runtime_observability_691038.py
python -m pytest -q tests/test_consolidation_guard.py
```

Run broader regression tests and smoke-test `/health` in a staging instance before any promotion. The patch intentionally **does not** alter heartbeat writer, scanning cadence, decision logic, broker access, settlement logic, or execution permissions. The existing full diagnostic heartbeat is retained for compatibility.

## Expected endpoint changes
- `scanner_process` always reports the observed heartbeat, including when `scanner_expected=false`.
- `scanner_process_expected` separately describes session expectation.
- `scanner_heartbeat_reason`, `scanner_heartbeat_error`, `scanner_heartbeat_fresh`, `scanner_heartbeat_stale_after_seconds` explain authority selection.
- `scanner_heartbeat_at` prefers the fresh scanner-owned timestamp.
- `memory_pressure` reports raw and estimated non-inactive-file usage, PSI and cumulative OOM events.

## Limitations
- An old consumer that expects `scanner_process.state=NOT_EXPECTED` after hours needs a compatibility review.
- A heartbeat older than 45 seconds still legitimately falls back; the reason is now visible.
- Cumulative OOM counters cannot prove an *ongoing* OOM; investigate deltas separately.
- A `HIGH_RAW_USAGE_NO_CONFIRMED_PRESSURE` classification does not guarantee future immunity from OOM.
- `memory_pressure` reads cgroup files synchronously on health requests. Verify request latency under production load.
