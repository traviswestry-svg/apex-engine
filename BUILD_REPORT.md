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
