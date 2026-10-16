# APEX Combined Runtime Stability & Signal Integrity — Candidate

## Authoritative baseline
`apex-engine-main(20261016-114804).zip`, reported release `69.10.37`.

## Merge audit
The October 16 baseline **already includes** the signal-integrity guard, volume-profile timing diagnostics, scanner-worker memory pairs, and paired diagnostic module/tests. The older independent candidate ZIPs each contain an `app.py` from different states; replacing the current `app.py` with either candidate would regress the other changes. This build retains the baseline `app.py` and merges **only the missing full-scan and scheduler event hooks**.

## Changed files
- `app.py` — diagnostic-only full-scan ATTEMPT/COMPLETED/FAILED/SKIPPED, paired FULL_SCAN memory measurements, and scheduler iterations. Existing signal guards and volume-profile timing preserved.
- `tests/test_combined_runtime_signal_integration.py` — regression checks for both integrations, no loss of guards or timing.

## Already present in baseline; deliberately NOT overwritten
- `engine/signal_integrity_guard.py`
- `engine/paired_runtime_diagnostics.py`
- `scanner_worker.py`
- `tests/test_signal_integrity_guard.py`
- `tests/test_paired_runtime_diagnostics.py`

## Read-only Render telemetry
- `/data/apex_runtime_memory_pairs.jsonl`
- `/data/apex_scan_coverage.jsonl`

## Validation and release conditions
Run focused tests, consolidation guard, and full CI against the integrated repository. Staging/production must verify full-session scanner coverage, absence of signal type errors, volume-profile latency, and cgroup OOM/pressure counters. No version bump or authority promotion is included. Existing production is not modified by this ZIP.

## Apply
Extract the ZIP at the **repository root**. It contains only changed files; review `app.py` diff first. Apply only if the checkout matches the October 16 baseline; otherwise merge/re-audit instead of overwriting `app.py`.
