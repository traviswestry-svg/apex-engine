# APEX — Decision-Time Volatility Source Acquisition & Shadow Candidate Validation

## Scope
Candidate **research-only additive patch** on reconstructed 69.10.47 source overlay. NOT production-certified or deployed. The latest complete uploaded repository was November 2; research candidate changes have been sequentially layered, but the actual deployed/merge branch SHA is not available. This ZIP includes only files changed from the previous source-availability research candidate.

## Changes
- `app.py`: forwards **already fetched** ES futures provider context to the Morning Brief. No new network request, provider auth, credentials or environment variables.
- `engine/morning_brief.py`: freezes `structured.forecast_provenance_diagnostics.expected_move.shadow_volatility_source_candidates` before canonical archival; does not modify selected expected move or daily levels.
- `engine/decision_time_volatility_candidates.py` (new): strictly bounded overnight ES realized five-minute log-return dispersion candidate; validates provider status, ES ticker, bar chronology/completeness, last completed timestamp and timestamp identity; rejects future bars and missing/stale samples. Projects the *uncalibrated* full RTH 78-bar one-sigma **ES-volatility proxy** in SPX point units, using SPX reference spot. It is NOT sourced from SPX options, is NOT validated IV, and is NOT a calibrated next-session forecast.
- `engine/premarket_directional_features.py`: read-only research visibility on canonical detail rows and exact-matched retrospective outcome rows; archives lacking the field stay legacy and are never reconstructed.
- `tests/test_decision_time_volatility_source_shadow_candidate.py` (new): tests valid sample, no-future evidence, missing/gapped/duplicate/stale data, timestamp failure, legacy visibility and non-mutation.

## Evidence limitations
The provider currently feeds delayed/fetched ES bars with source timestamps but no separate verifiable quote entitlement declaration. No provider failure is inferred. This is a **distinct realized-volatility proxy**, not a substitute for the missing fresh two-sided SPX option market. The conversion assumes five-minute return dispersion propagates to 78 RTH bars without calibrating returns, gap/jump risk, ES-to-SPX basis, holidays/half days, or intraday regime changes. It is deliberately only a shadow candidate. APEX must collect multiple future outcomes before calculating calibration or performance claims. Historical samples are not backfilled.

## Validation and release blockers
- Selected tests covering source availability/integrity, source segmentation, premarket features, canonical identity, consolidation, gamma coverage, gamma stability and gamma-transition passed **89 tests** (see actual test log; count is based on this candidate's run).
- Full pytest stops in collection: `ModuleNotFoundError: No module named 'flask'`; project runtime requirements are not installed in this environment.
- `test_preparation_then_same_day` in prior `tests/test_morning_same_day_lifecycle_candidate.py` still expects `CANONICAL_ARCHIVED`, while later cumulative code classifies the same-day canonical record `CANONICAL_SAME_DAY_ARCHIVED`. This is an existing cross-candidate test expectation mismatch, not changed in this candidate. ES session-boundary regressions identified in previous builds remain unresolved.
- Before deployment: install requirements, run full CI and release-truth / configuration registry tests, gamma-transition/ES sessions, reconcile source overlay with actual deployment SHA, and validate a staging Morning Brief archive/research readback.

## Hard invariants
Canonical release remains 69.10.47. No forecast or official scoring changes. No trading execution or paper broker authority. No database schema, cron, environment-variable, or manifest updates. No new network calls. No post-decision data. No claiming verified implied volatility.
