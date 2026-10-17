# APEX Post-Scan Deadline Protection — candidate

Changed-files-only patch, based on the October 16 repository plus the prior cross-process scanner coverage candidate. Keeps release `69.10.37`, broker execution disabled, and existing scanner coverage journal.

## Scope
- Measure post-scan work starting after `run_scan_once()` returns; previous `last_post_scan_duration_seconds` incorrectly included full scan time.
- Report separate `last_scheduler_cycle_duration_seconds` and post-scan `auxiliary`, `flow_learning`, `legacy_settlement` stage timings.
- Defer optional flow sampling/feature writing when the configured freshness window has less than 45 seconds remaining. Defer legacy scanner-owned settlement on the same condition (the separate canonical settlement scheduler is untouched).
- Preserve serial execution and canonical evidence ownership; no new threads, overlapping SQLite writers, synthetic labels, or broker authority.
- Continue existing adaptive sleep and persistent scanner coverage.

## Limits and validation
This is **cooperative stage-boundary isolation**, not hard preemption: in-flight API/DB calls cannot be interrupted. The auxiliary phase (IOS, tracking, signal evaluator, premium grading) remains synchronous and may still exceed the freshness window. Flow work can also exceed the deadline after it starts. Production timing must determine whether deeper workload separation is warranted. No full-repository CI or live Render test performed.

Run `python -m pytest -q tests/test_post_scan_deadline_protection.py tests/test_scanner_coverage_authority.py tests/test_scanner_cadence_continuity_closure.py`.
