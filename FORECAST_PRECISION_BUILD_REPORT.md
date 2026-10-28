# APEX Forecast Precision & Adaptive Calibration Validation — candidate

Baseline: uploaded APEX 69.10.47 repository plus previously delivered standalone shadow-calibration candidate.

## Changes
- Integrates existing chronological, read-only shadow calibration research into the Research Lab route registry at `GET /api/research/forecast-precision`.
- Adds out-of-sample baseline vs shadow comparisons for center MAE, maximum-excursion MAE, containment, and projected/realized range-width ratio.
- Adds archive-wide signed range-center, width, and move biases, exact regime accuracy, and projected-to-actual regime confusion counts.
- Excludes ambiguous duplicate canonical session dates and incomplete recaps; reports insufficient history rather than promoting an untested model.
- Maintains official forecast immutability, historical score weights, and paper-execution boundaries.

## Validation
- `python -m pytest -q tests/test_forecast_precision_validation.py tests/test_morning_forecast_shadow_calibration.py`: 7 passed.
- `python -m py_compile engine/morning_forecast_shadow_calibration.py engine/institutional_research_lab_v243_routes.py`: passed.

## Limitations
- No actual production archive available; no real historical performance claim.
- JSON API endpoint integrated, but no HTML dashboard component or navigation added in this candidate.
- The research-only API does not modify Morning Brief generation or trading decisions.
- Full repository CI and live production integration not run.
- Endpoint uses the existing Research Lab route registration; deploy requires that registry be enabled.
- The prior shadow-calibration module is bundled in this patch, so apply to the uploaded baseline rather than stacking the earlier shadow ZIP on top.
