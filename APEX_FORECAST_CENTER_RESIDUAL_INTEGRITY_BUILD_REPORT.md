# APEX — Forecast Center Residual Integrity & Range Containment Attribution Validation

## Baseline and scope
- Baseline: `apex-engine-main(20261102-231112).zip` with the canonical-selection, agreement-explainability, and latest directional-magnitude patches overlaid in that order.
- Canonical release version remains `69.10.47`; no manifest or governance registry changes.
- Research read-only; no changes to canonical writer, Morning Brief selection, Evening Recap grading, or execution authority.

## Changed files
- `engine/premarket_directional_features.py`: adds `forecast_center_integrity()`, validates the frozen `structured.expected_move.lower/upper` against recap projected bounds, validates actual session high/low against recorded extraction, checks authoritative official containment result, and cross-checks existing `forecast_error_diagnostics.range` when available. Separately provides frozen/realized low/high, centers, widths, signed center residual, high/low errors, width error, containment and boundary exceedances, frozen reference spot, and metric semantics. Inconsistent or unverifiable joins are excluded from shadow outcome attribution and listed in `shadow_outcome_attribution.integrity_exclusions`.
- `tests/test_forecast_center_integrity_candidate.py`: new tests for decomposition, containment misses, mismatches, and no inferred absent frozen ranges.
- `tests/test_premarket_magnitude_conflict_outcome_candidate.py`: adjusts synthetic fixtures to include the legitimate frozen projected range and official containment result now required by the new verification gate.

## Validation executed
- Targeted plus selected premarket, gamma, consolidation regression checks: **63 passed**, command `python -m pytest -q tests/test_premarket_magnitude_conflict_outcome_candidate.py tests/test_forecast_center_integrity_candidate.py tests/test_premarket* tests/test_consolidation_guard.py tests/test_gamma* --disable-warnings --maxfail=1`.
- Compilation: passed for changed modules and tests.
- Full repository CI attempt: **blocked during collection** at `tests/test_adaptive_confidence_calibration.py` due to missing environment dependency `flask`. This is not a passing full CI result. Release smoke tests and app boot were not certified.
- Gamma-transition regression represented by selected gamma tests; complete CI and production validation still pending.

## Production check and interpretation
- After full CI in dependency-complete environment and staging deployment, read `/api/research/premarket-directional-features?limit=10`.
- Inspect `shadow_outcome_attribution.rows[].forecast_center_integrity` for the October 30 record. Confirm original expected high/low, actual high/low, signed high/low errors, center residual and containment side. Any mismatch is excluded and included in `integrity_exclusions`.
- The previously reported October 30 residual (-137.585 SPX points) is **not certified by this local build**, because the production source records were not available locally for that exact-range audit.
- A valid retrospective midrange residual is **not** SPX open-to-close direction. The official `MAX_ABS_EXCURSION_FROM_FROZEN_MORNING_SPOT` metric is unchanged and must not be confused with session high/low width.
- Historical canonical or feature records are never backfilled or modified.
