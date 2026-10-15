# APEX Paired Memory Attribution & Scanner Coverage Candidate

Baseline: user-uploaded `apex-engine-main.zip` (October 15). This is a changed-files-only patch; production release metadata stays at 69.10.37.

## What changes
- `scanner_worker.py`: paired per-heartbeat and evidence/settlement/tick-feed RSS/PSS/private-dirty memory snapshots with cycle identity.
- `app.py`: full scan ATTEMPT/COMPLETED/FAILED/LOCK_BUSY events and paired FULL_SCAN memory; scheduler iteration evidence.
- `engine/paired_runtime_diagnostics.py`: bounded read-only JSONL diagnostics, failure-tolerant writes.
- `tests/test_paired_runtime_diagnostics.py`: focused tests.

## Production files
- `/data/apex_runtime_memory_pairs.jsonl`
- `/data/apex_scan_coverage.jsonl`

## Validation
Run `python -m pytest -q tests/test_paired_runtime_diagnostics.py` and the full repository CI suite before deployment. Use staging to confirm scan cadence unchanged.

## Cautions
- Observability only. No broker execution, scan schedule changes, settlement label changes, or database schema changes.
- These files capture only scanner process memory; stage deltas cannot attribute all native allocations or independent child threads.
- A full-scan event appears only when the scheduler actually invokes `run_scan_once`. `SCHEDULER_ITERATION` records the scheduler's loop cadence, not proof of market data completeness.
- Diagnostic failures are intended to fail open; test under production filesystem permissions.
- Never merge this candidate over a newer source revision without reconciling differences.
