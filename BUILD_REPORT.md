# APEX 69.10.48 — Morning Forecast Snapshot Integrity & Adaptive Calibration Validation

Baseline: apex-engine-main(20261026-232707).zip (69.10.47).
Delivery: changed-files-only candidate. No release-manifest bump; not production-certified.

## Implemented
- Deterministic structured snapshot SHA-256 identity for each Morning Brief response.
- Fail-closed narrative cache reuse when snapshot identity changes or provenance is missing.
- Numeric disagreement detection for explicit developing POC, VAH, and call-wall mentions.
- Async narrative status endpoint suppresses a completed narrative when an explicit discrepancy is found against the latest in-process deterministic snapshot.
- Frontend handles SNAPSHOT_MISMATCH as a narrative-unavailable condition.
- Separate forecast-quality dimensions; calendar coverage is NOT_VERIFIED, and forecast confidence is NOT_HISTORICALLY_CALIBRATED.
- Explicit calibration validation status HISTORY_NOT_CONNECTED, zero training and holdout sessions, and promotion_authority=false.
- Official forecast values, archive semantics, execution authority, and adaptive shadow behavior unchanged.

## Verification
17 focused tests passed; py_compile passed.

## Known limitations / release blockers
- Async narratives are keyed by target date and mode, not snapshot fingerprint. A same-session completed narrative may be reused when its numeric claims are not explicitly detected; PARTIALLY_CHECKED/NOT_VERIFIABLE is not proof of snapshot binding. Full closure requires snapshot-keyed async job identity and persistence migration.
- Numeric check covers explicit named fields only, not free-form paraphrases or every institutional level.
- Historical forecast/outcome records are not wired to the calibration evaluator; no real walk-forward improvement measured.
- No full repository CI or production deployment validation was performed.
- Keep candidate in shadow mode; do not promote calibration or call the release production-complete.

---

# Adaptive Morning Forecast Calibration — shadow candidate

Base repository: uploaded APEX 69.10.47. Release manifest unchanged.

Includes read-only robust median calibration for prior verified sessions and a walk-forward evaluator. The morning brief emits an INSUFFICIENT_VERIFIED_HISTORY shadow diagnostic by default: it deliberately does not load outcome history on the live request path. No live forecast modification, performance claim, historical backfill, execution change, or automatic promotion.

Offline evaluation requires the operator to supply completed session rows with frozen forecast provenance, spot, expected move, realized high/low, and explicit outcome_complete=true. At least 20 unique prior sessions required. Candidate scaling bounded to 0.75–1.5 and center shift bounded to +/-0.5 sigma. All historical records excluded from own training date; duplicate session dates excluded.

Focused tests: 6 passed. Python compilation passed. Full CI, production load, and historical backtest not run. Do not deploy as an accuracy-improving model without genuine historical walk-forward evidence.

---

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
