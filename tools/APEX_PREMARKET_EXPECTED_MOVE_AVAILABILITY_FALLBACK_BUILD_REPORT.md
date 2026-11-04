# APEX — Premarket Expected-Move Source Availability & Decision-Time Fallback Research

## Candidate status
Research-only additive candidate. **Not production-certified.** Canonical APEX release remains `69.10.47`. Generated from the November 2 repository plus the later preserved cumulative research candidates. This package contains only changed files relative to the prior source-quality-segmentation candidate.

## Modified files
- `engine/premarket_expected_move_availability.py` **NEW**: `capture()` freezes quote availability context and hypothetical fallback inventory from pre-decision evidence. `visibility()` reads only the frozen canonical record, returns `LEGACY_AVAILABILITY_NOT_ARCHIVED` if absent.
- `engine/morning_brief.py`: freezes `structured.forecast_provenance_diagnostics.expected_move.premarket_source_availability` before canonical persistence, after capturing the existing option-source audit.
- `engine/premarket_directional_features.py`: exposes `details[].premarket_expected_move_source_availability` and exact-matched completed `shadow_outcome_attribution.rows[].premarket_expected_move_source_availability` from immutable Morning Brief data.
- `tests/test_premarket_expected_move_source_availability_candidate.py` **NEW**: source, time, freshness, no-hindsight, archive, missing-data, and fallback cases.

## Evidence contract
- Distinguishes being outside the **US regular-session clock** (9:30–16:00 ET weekdays, simplified clock only) from actual availability of SPX options/global-hours trading. It does **not** claim that SPX options were unavailable for trading, or that provider or entitlement failure occurred.
- Uses original provider leg event timestamps; no substitution of capture time for source time. Validated freshness requires both positive two-sided mids, archived ages and independently computed ages within 120 seconds, and source audit status `SOURCE_VERIFIED` without issues. The separate existing quote audit remains authoritative.
- If frozen call and put quote dates precede the forecast ET day and use last-trade pricing, classifies as `PRIOR_DAY_LAST_TRADE_FALLBACK_ONLY`, never fresh.
- Prior-day straddle hypothetical is descriptive only and retains historical source quality. If archived IV, time-to-expiration and reference spot exist, computes a numeric hypothetical `spot * iv * sqrt(t)` labelled `NUMERIC_IV_AVAILABLE_SOURCE_UNVERIFIED`; **never** upgrades to verified source without independent provenance.
- `provider_status_as_reported` only if explicitly passed upstream; no inference of entitlement or outage from missing quotes. Existing caller generally passes provider-specific quote evidence without a provider status, so the reason remains unknown.
- All historical canonical Morning Briefs lacking the new field remain `LEGACY_AVAILABILITY_NOT_ARCHIVED`, without reconstruction or changes to snapshots.
- Does not change straddle-first/IV-fallback selection, official forecast, Evening Recap grading, execution authority, DB or env registry.

## Tests and release blockers
- 85 selected tests passed, including new source-availability tests, source quality, quote integrity, premarket, consolidation, gamma coverage and gamma stability.
- `compileall` passed for changed modules and the new test.
- Full `pytest -q --maxfail=1` blocked during test collection: `ModuleNotFoundError: No module named 'flask'` in `tests/test_adaptive_confidence_calibration.py`. Full CI is **not** certified.
- Separate ES session-integrity run: 1 failed, 3 passed; `test_mixed_dates_select_latest_complete_session` (`KeyError: prior_day_range_position`). This test concerns unchanged upstream ES code and was a known baseline issue; it remains unresolved and must be verified against the merge target.
- Before deployment, install project dependencies, run entire repository CI and release-truth/gamma regression suite, reconcile the actual deployment SHA, test canonicity and the new frozen field in a staging Morning Brief.

## Expected November 4 handling after future collection
Previously archived 2026-11-04 Morning Brief will show `LEGACY_AVAILABILITY_NOT_ARCHIVED` for this **new** diagnostic, even though its older frozen quote audit exists and says `DEGRADED_SOURCE_EVIDENCE`. This is deliberate: historical records are immutable. Future equivalent evidence should be classified `PRIOR_DAY_LAST_TRADE_FALLBACK_ONLY` from its frozen snapshot, if a new forecast is generated.
