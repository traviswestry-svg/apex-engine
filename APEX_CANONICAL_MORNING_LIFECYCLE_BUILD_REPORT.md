# APEX — Canonical Morning Brief Lifecycle & Same-Day Forecast Discovery Validation

Base repository: October 30 2026 full repository plus the October 31 premarket availability patch. Canonical manifest remains 69.10.47.

## Proven code issue
`_official_forecast_eligibility()` previously allowed `NEXT_SESSION_PREP` reports to reserve a single-row `apex49_morning_snapshots` slot for their target session, before the target session arrived. The later, eligible same-day PREMARKET report would then be recorded only as a revision. No historical records were modified by this candidate.

## Changes
- `engine/evening_recap.py`: new canonical eligibility requires a same-day pre-opening PREMARKET context (or same-day legacy pre-opening context). NEXT_SESSION_PREP is persisted as a revision only. A previous-date PREMARKET is rejected.
- `engine/premarket_directional_features.py`: existing research diagnostics now include revision-only dates, a bounded per-date lifecycle inventory, count of qualifying same-day revisions, and diagnostic classification when a revision exists but canonical does not. The diagnostic does not create or mutate official records.
- `tests/test_morning_same_day_lifecycle_candidate.py`: validates prep followed by same-day official, prep-only, same-day-only + immutable later revision, and previous-day premarket rejection.

## Validation in this environment
- Premarket and canonical tests: 22 passed.
- Consolidation governance: 4 passed.
- Gamma suites: 60 passed.
- Python compilation: passed.
- Full repository: blocked in collection (68 errors), including missing Flask dependency. Full CI, governance/release-truth matrix, and production integration tests not completed.

## Deployment and preservation
- Changed-files-only artifact. Apply onto repository containing prior premarket availability diagnostics patch.
- No release metadata increment; no new environment variables.
- Never mutate pre-existing canonical rows. If historical prep occupied canonical storage, this patch DOES NOT silently replace it; investigate with an explicit migration proposal and preserve evidence.
- No changes to official forecast selection for already archived records, evening grading, risk, decision authority, or execution authority.
- Confirm new post-deployment PREMARKET records via `/api/research/premarket-directional-features?limit=15` and inspect `details[].lifecycle`.
- Candidate not certified for production until complete CI and staging tests pass.
