# APEX — Premarket Feature Completeness & Evidence-Quality Validation
Candidate date: 2026-10-30. Based on uploaded APEX 69.10.47 repository. Shadow research only.

## Changes
- `engine/premarket_feature_provider.py`: derive `premarket_trend_strength` only from six consecutive, completed, same-window ES 5-minute OHLC bars; normalized terminal displacement over the observed high-low envelope. Zero observed envelope => abstention.
- `app.py`: reuse already-fetched futures bars to supply pre-existing previous-RTH bar observations to the adapter; exclude raw bars from archived futures-feed summary. No new provider request.
- `engine/premarket_feature_provider.py`: derive `prior_day_range_position` only from at least 75 distinct prior-RTH 5-minute bars, both open and close boundaries, valid OHLC, with all timestamps preceding the overnight window and decision. Value is ES last overnight close's position relative to previous RTH ES H/L and may be outside [0,1]. It is NOT SPX cash range position.
- Gamma context remains missing: the provided repository does not establish a verified, decision-time, comparability-checked gamma feature input suitable for this path. No synthetic values or unsafe fallback introduced.
- Added five focused tests covering success, missing/partial bars, missing gamma and archive nonmutation.

## Verification
- Focused tests: 14 passed (existing and new premarket feature tests).
- Existing gamma regressions: 11 passed.
- Python compilation of edited modules: passed.
- Full repository pytest: blocked at collection by `ModuleNotFoundError: No module named 'flask'` in this runtime; not certified.
- No new environment variables, release metadata, database schema, trading routing, or authority changes.
- Production data-provider integration, audit of full repository CI/governance, and postdeployment immutable snapshot retrieval still required.

## Integration caveats
- Provider bars are 5-minute timestamps presumed to be open times, with end time computed from interval; source timestamp semantics must be checked against production adapter.
- Missing regular-session bars (including on Monday if the existing three-day fetch omits Friday), incomplete coverage, holes in last six premarket bars, absent OHLC or zero range generate abstentions.
- Prior RTH observation is supplied only using the existing fetch, so coverage can be unavailable; the currently supplied code's lack of exhaustive prior session grouping means partial/multi-day provider feeds must be assessed in production before wider release.
- Added features do not affect the deterministic three-vote shadow direction classifier; further classifier experiments require accumulated immutable out-of-sample data.

## Deployment
1. Apply changed files only to a staging checkout with same release baseline.
2. Install repository requirements; run full CI/governance and gamma transition suite.
3. Confirm original frozen Morning Brief is unchanged and fresh next-session Morning Brief has feature statuses with honest missing/available states.
4. Review provider timestamps / ES contract roll behavior; only then consider promoting candidate to production.
