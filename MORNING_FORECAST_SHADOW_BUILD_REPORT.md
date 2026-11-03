# APEX 69.10.47 — Adaptive Morning Forecast Calibration (Shadow Research Candidate)

## Scope
- Added `engine/morning_forecast_shadow_calibration.py` with archived recap extraction, provenance and metric checks, strictly chronological median-bias calibration, and walk-forward comparison.
- Added four focused tests covering abstention, improvement on synthetic stable bias, leakage prevention, provenance rejection, and duplicate-date exclusion.
- No release version bump; no route/UI wiring; no production forecast modification, broker permissions, scoring changes, or database writes from calibration logic.

## Methodology
- Uses only existing completed recap archives carrying `forecast_id` and `forecast_snapshot_hash`.
- Excludes recaps with incomplete inputs, missing expected-move semantics, or ambiguous duplicate session dates.
- Requires at least 20 prior eligible sessions by default. Each evaluated session uses only earlier completed session observations.
- Computes rolling median errors for center, width, and maximum absolute excursion from frozen morning spot; compares shadow to unchanged baseline on center MAE, move MAE, and range containment.
- Does not promote shadow forecasts or make trading decisions. No actual archived performance figures are asserted: production database was not supplied.

## Validation
`python -m pytest -q tests/test_morning_forecast_shadow_calibration.py` — 4 passed.

## Remaining before production promotion
1. Integrate a read-only admin/Research Lab endpoint with authorization and safe caching; review persisted archive cohort size and completeness.
2. Backtest on genuine completed-session archives, evaluate temporal robustness, confidence intervals, regime splits, and conservative deployment gates.
3. Audit morning reference-price freshness and narrative/regime consistency separately.
4. Run full CI and resource/memory profiling; no production release approval implied.
