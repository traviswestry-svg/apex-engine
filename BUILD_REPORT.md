# APEX 69.10.38 — Scanner Lifecycle Reconciliation & Canonical Evidence Integrity Closure

## Delivery status: PARTIAL CANDIDATE — NOT RELEASE READY

Base repository: apex-engine-main(20261020-201823).zip. Canonical manifest remains 69.10.37 intentionally: the requested complete 69.10.38 scope has not yet been implemented or validated.

## Implemented
- Scanner-owned journal schema v2: additive `attempt_id` column and index, legacy rows retained.
- Per-invocation UUID generated in `run_scan_once`, propagated to ATTEMPT, COMPLETED, FAILED and LOCK_BUSY journal events.
- Journal rejects duplicate ATTEMPT IDs, unmatched terminal IDs, cross-process terminal IDs and duplicate terminal outcomes.
- Read-only cross-process `attempt_reconciliation` with paired/recent/stale counts, legacy uncorrelated counts and bounded stale examples. Stale unmatched attempts are UNCONFIRMED, not failures.
- Existing settlement exact-ID diagnostics, postscan budget and authority gates retained unchanged.

## Not implemented / not claimed
- Canonical feature-to-excursion identity divergence root cause repair; requires production row-level evidence or reproducible local fixtures. No synthetic P/L or fuzzy joins added.
- Durable cross-process postscan phase telemetry and source last-success probes.
- Production migration/deployment validation and full CI.

## Tests
26 focused tests passed including scanner lifecycle, settlement identity, scheduler cadence and postscan deadline. Python compile succeeded. No full suite or Render deployment was run.

## Changed files
- app.py
- engine/scanner_coverage_authority.py
- tests/test_apex_69_10_38_scanner_reconciliation.py

## Safety
No broker execution, trade decision or label authority changes. No release manifest bump.
