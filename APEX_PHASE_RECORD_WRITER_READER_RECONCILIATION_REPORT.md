# APEX Phase-Record Writer/Reader Reconciliation — Candidate

**Baseline:** APEX 69.10.47 (`Paper Execution Lifecycle Validation`). Based on `apex-engine-main(20261106-121700).zip` after applying the Runtime Memory, Health Response Memory, and Scanner/Settlement Phase Attribution candidates **in that order**.

## Observed production problem

The 2026-11-10 17:01 ET `/health` report included `scanner_settlement_phase_memory_attribution.status=NO_VERIFIED_PHASE_PAIRS`, `verified_records=0`, a ~1.53 MB JSONL file and a bounded 128 KiB tail read. Existing reader silently rejected records without showing why. No assertion that the writer had failed was justified by the report alone.

## Changes

* Existing bounded reader now provides `reconciliation.classification_counts`, including `VERIFIED`, `MALFORMED_JSON`, `NON_OBJECT_JSON_RECORD`, `UNSUPPORTED_STAGE`, `UNSUPPORTED_PAIR_SCHEMA`, `MISSING_OR_INVALID_PROCESS_IDENTITY`, `UNVERIFIED_PROCESS_IDENTITY`, `MISSING_PHASE_BOUNDARY`, `MISSING_PROCESS_RSS`.
* Provides `candidate_records`, `evaluated_lines`, `stage_counts`, `writer_identity_diagnostic_counts`, `tail_window_truncated`, `same_process_scan_and_settlement_present`, and an explicit interpretation.
* Original status and phase summaries remain backward-compatible. `PHASE_PAIRS_AVAILABLE` can mean one stage type alone; use the explicit same-process boolean to verify both phase types.
* Writer emits a small `identity_diagnostic` enum (`VERIFIED`, `PROCESS_START_UNAVAILABLE`, or `PROCESS_IDENTITY_CHANGED`) without changing the existing `process_identity_verified` boolean.
* Strict PID + positive Linux process start ticks are mandatory for eligibility. No PID-only joins, inferred identity, synthetic data, new trading authority, new configuration variables, database access, log-wide scans, or memory reclamation.
* Reader inspects at most 128 KiB / 64 complete JSONL lines, does not retain response bodies, and does not add new endpoints.

## Integration

After the earlier three candidate patches are reconciled into the current branch, replace `engine/scanner_settlement_phase_memory_attribution.py` with the included version, apply `APEX_PHASE_WRITER_RECONCILIATION.patch` using `patch -p1`, and add the test file. Keep existing `/health` wiring intact. The patch is specifically against the **earlier phase attribution writer** and will not apply cleanly to the original November 6 source alone.

## Validation

* **60 selected tests passed** across phase writer/reader round trip, legacy/malformed tail, PID reuse, settlement scheduler, runtime memory, health response, gamma, settlement integrity, consolidation, and release-truth regression checks.
* Python compileall passed for changed modules and tests.
* Full `pytest -q --maxfail=1` attempted and halted during collection: local `flask` package missing. **Not production-certified.** Require complete repository CI and current-deployment source reconciliation before release.

## Production acceptance criteria

1. `/health` shows `scanner_settlement_phase_memory_attribution.reconciliation.classification_counts` and `stage_counts`, with counts bounded to the inspected tail.
2. Newly written phase records include `identity_diagnostic` and compatible `process_pid`, `process_start_ticks`, `process_identity_verified` fields.
3. If `verified_records=0`, use counts to distinguish legacy identity, incomplete measurements, unknown stages, unsupported schema or JSON errors; do **not** infer the missing process identity.
4. After a real FULL_SCAN or settlement pass, verify `VERIFIED > 0` and a corresponding stage count. Scanner and settlement may be different process instances; a false `same_process_scan_and_settlement_present` is expected in that case and does not signify missing observations.
5. Confirm zero change in scanner completion, settlement eligibility, authorization, and evidence lifecycle; compare cgroup and RSS only within verified process instances.

**Note:** `source_bytes` may be much larger than `bounded_read_max_bytes`; the reader only classifies the window it examined. Existing writer rotation may replace the file when the 2 MB limit is reached, resetting available history without changing identity eligibility.
