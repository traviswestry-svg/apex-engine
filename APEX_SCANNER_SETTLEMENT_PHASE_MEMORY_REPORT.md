# APEX Scanner/Settlement Phase Memory Attribution — Candidate

**Release baseline:** APEX 69.10.47, `Paper Execution Lifecycle Validation`.
**Source:** `apex-engine-main(20261106-121700).zip` plus the previously supplied Runtime Memory Attribution and Health Response Memory & Serialization Attribution candidate patches. **Not deployed.**

## Scope

- Enhance existing `engine/paired_runtime_diagnostics.py` phase records with scanner process PID, Linux `/proc/PID/stat` start-time ticks, and verified before/after process identity. Existing `FULL_SCAN` checkpoints are retained without changing scanner execution.
- Instrument the *actual* `feature_store_writer.settle_pending_labels` call in `engine/flow_settlement_scheduler.py` using existing paired-memory `SETTLEMENT_PASS` stage capture; use a `try/finally` that also records failure observations. The diagnostic is fail-open and does not affect settlement decisions or durable settlement result fields.
- Add `engine/scanner_settlement_phase_memory_attribution.py` to safely read at most **128 KiB / 64 recent records** from the existing phase-memory JSONL (default `/data/apex_runtime_memory_pairs.jsonl`), excluding unverified and legacy process identities. No DB queries, broad directory walking, scanning history in full, GC, or automatic memory reclamation.
- Expose `scanner_settlement_phase_memory_attribution` as a small field in the existing `/health` response. Group last observed scanner/settlement stage deltas by **PID and process start-time ticks**, never merely PID or deployment version. Provide RSS, private dirty, cgroup anon/file/current deltas, max/OOM event deltas, sample counts and bounded phase summaries.
- Existing runtime memory and health serialization candidates remain intact; no duplicate route, no execution authority, no database schema changes, no additional configuration variables.

## Test results

- **68 selected tests passed**: new phase attribution tests, existing paired runtime, previous two memory candidates, scheduler closure, settlement integrity, gamma integrity, release truth, consolidation guard and runtime wiring.
- `compileall` of all edited/new Python sources passed.
- Full repo `pytest -q --maxfail=1` attempted and failed **during test collection** due to missing `flask` Python package in local environment; this is not full CI certification.
- No release manifest/version changes. Production CI/release-truth and integration smoke tests must run with project dependencies installed and up-to-date branch reconciled before deployment.

## Production verification

1. Deploy only after full CI and review. Preserve APEX `SHADOW_RESEARCH_ONLY`, no broker activation.
2. Check `/health` for `scanner_settlement_phase_memory_attribution.status` and `processes[].phases.FULL_SCAN` / `SETTLEMENT_PASS`.
3. Initially `NO_VERIFIED_PHASE_PAIRS` is expected because legacy records lack start-time identity. After scans and actual settlement calls, look for `PHASE_PAIRS_AVAILABLE`. Cadence-skipped settlement cycles do not create phase pairs.
4. Compare only records with identical `pid` **and** `process_start_ticks`, and correlate timestamps with `/health` RSS. Differences can include unrelated concurrent activity. The endpoint does not identify a Python heap/SQLite cache cause or prove a leak.
5. If memory-limit events rise again, prioritize operational stabilization and log collection; do not delete databases or their WAL files.

## Files

- `APEX_SCANNER_SETTLEMENT_PHASE_INTEGRATION.patch`: applies after the two prior memory candidate integration patches.
- `engine/scanner_settlement_phase_memory_attribution.py`: bounded parser and attribution summarizer.
- `tests/test_apex_scanner_settlement_phase_memory_attribution.py`: integrity, PID-reuse, tail, telemetry isolation, scheduler wiring tests.
