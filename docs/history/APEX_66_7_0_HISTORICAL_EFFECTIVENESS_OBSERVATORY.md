# APEX 66.7.0 — Historical Effectiveness Observatory

## Purpose
Read-only measurement of persisted APEX predictions against governed `GRADED` outcomes. The Observatory does not grade, infer missing history, recalibrate, promote policies, or change execution authority.

## Dashboard
- `/apex_os/effectiveness`

## APIs
- `/api/effectiveness/observatory?symbol=SPX`
- `/api/effectiveness/health?symbol=SPX`

## Measurements
- Overall observed directional hit rate
- Mean captured evidence score and diagnostic calibration gap
- Average directional move, MFE, and MAE
- Breakdowns by horizon, confidence bucket, setup, session period, market regime, gamma regime, volatility regime, and auction regime
- Exclusion counts and evidence-pipeline readiness

## Horizon integrity
SCALP / INTRADAY / SWING are measured only when those directions were captured in the historical decision snapshot. Missing horizons are not inferred from grading duration. Horizon confidence uses the captured horizon-specific confidence.

## Codespaces / deployment
No absolute local paths were added. Database resolution continues through the existing `APEX_EVIDENCE_PIPELINE_DB` / repository-relative evidence-pipeline behavior, so the changed files can be uploaded into the same repository paths in Codespaces.

## Validation
- New Observatory unit tests: 2 passed
- Targeted regression set: 14 passed, 1 skipped because Flask is not installed in the audit sandbox
- Python compileall: passed
- Static route-registration check: passed
