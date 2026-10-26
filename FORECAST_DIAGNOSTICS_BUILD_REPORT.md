# APEX Forecast Error Attribution — candidate patch

Baseline: uploaded APEX 69.10.47 repository. Release manifest unchanged.

## Changes
- `engine/evening_recap.py`: adds read-only error attribution to canonical recap comparison and deterministic Markdown. Reports high/low/center/width error, maximum excursion relative to frozen spot, and exact regime match separately from compatible-family grading.
- `tests/test_apex_forecast_error_attribution_candidate.py`: three focused regression tests, including the October 26 screenshot numbers and missing-data fail-closed behavior.

## Validation
`pytest -q tests/test_apex_forecast_error_attribution_candidate.py tests/test_apex_69_10_3_morning_forecast_evening_validation_integrity.py` — **8 passed**.
`python -m py_compile engine/evening_recap.py` — passed.

## Boundaries
No change to official score, grade, weights, immutable morning snapshot, release manifest, or execution authority. No historical backtest or adaptive forecast recalibration is included. October 26 regression uses screenshot-derived values and illustrative intraday bars consistent with those extrema; it is not a replay of the actual session.
