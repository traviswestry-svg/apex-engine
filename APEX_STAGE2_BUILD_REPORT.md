# APEX Stage 2 — SQLite Read-Side I/O & Cross-Process Memory Correction (Candidate)

**Release:** 69.10.47 unchanged. **Status:** local candidate; NOT deployed / NOT full CI certified.

## Evidence and scope

November 12 production snapshots showed an approximately 1.19 GiB cgroup memory increase within a 33-second scanner phase, principally file-backed, even though scanner RSS increased ~42 MiB. This phase correlation does **not** isolate SQLite or identify a causal process. It is not safe to clear file cache, VACUUM live databases, force SQLite checkpoints or garbage collection, or discard canonical evidence based on this evidence.

Source examined: `apex-engine-main(20261106-121700).zip` with the prior Stage 1 heartbeat-compaction implementation present in the working tree. **No up-to-the-minute production repository was provided.** Integrate the patch into the currently deployed branch, reconcile any intervening edits, and run CI.

## Concrete corrected paths

1. `engine.trigger_observatory.predictive_validation()` previously loaded `decision_id,session,action,snapshot_json` for **every decision in the evidence DB** and graded horizon metadata for **every grade**, even though the report's trigger cohort only needs linked `decision_id`s. It now queries exact linked IDs in batches of <=256 bind parameters, streams cursor rows, and closes read-only SQLite connections explicitly using the canonical connection context manager.
2. `_attach_window_metrics()` previously fetched **every historical trade-trigger price observation** and materialized dictionaries for all triggers. It now streams only observations with exact trigger IDs from the requested report cohort, in <=256-ID batches, and always closes its read-only connection. No cross-trigger borrowing or nearest-time matching.
3. `learning_readiness()` matured trigger summary previously materialized an unbounded list and used `with connect()` which does **not** close Python sqlite3 connections. It now iterates the cursor inside `canonical_connection` which guarantees close.
4. An independent, optional one-shot `cross_process_snapshot.py` reports per-PID Linux process start ticks, `/proc/*/status`, `/proc/*/smaps_rollup`, and cgroup anon/file/active_file/inactive_file/events. It does not execute inside scanner/health paths, query SQLite, or mutate process state; it is an operator verification aid. Permission and /proc visibility limit interpretation.

### Non-goals and cautions

- No database migration, index creation, retention deletion, WAL checkpoint, `PRAGMA mmap_size`, `PRAGMA cache_size`, or system cache clearing.
- No change to scanner cadence, feature and evidence ownership, trade execution, decision logic, or settlement eligibility.
- Batch-scoped exact queries assume the evidence and observation stores maintain their existing ID indexes. Check `EXPLAIN QUERY PLAN` in production against actual schemas if latency worsens.
- This **reduces redundant application-level reads and materialization**; it is **not proof of a reduction in Linux file cache**, memory leaks, or `memory.events.max`. The scanner's largest file-cache swing has not been causally isolated.
- The observed before/after snapshots came from different process/container instances. Do not interpret the restart as proof of a fix.

## Validation

- Selected Trigger Observatory + settlement + gamma + consolidation + release-truth tests: **92 passed**.
- Operator cross-process snapshot source test: **1 passed**.
- `python -m py_compile`: passed for modified module and operator script.
- Full `pytest --maxfail=1`: **blocked at collection**, `ModuleNotFoundError: No module named 'flask'`; full configured CI remains mandatory.
- No new environment variables or canonical release truth changes.

## Integration

Apply `APEX_STAGE2_SQLITE_IO_CORRECTION.patch` on the production branch at repo root (review context first), or cherry-pick `engine/trigger_observatory.py` *only after comparing current production edits*. Add `tests/test_apex_stage2_sqlite_io_bounding.py`. `cross_process_snapshot.py` is an optional one-shot operator tool, **not** a runtime change.

After deployed, verify `predictive_validation()` results and horizon/integrity grouping match pre-change fixtures and compare: cgroup `memory.events.max`, `anon`, `active_file`, `inactive_file`, web/scanner RSS and PID start identity, endpoint latency, and scanner coverage across the same process/cgroup. Also verify heartbeat compaction from Stage 1 persists. Prefer parallel non-invasive testing and an easy rollback.
