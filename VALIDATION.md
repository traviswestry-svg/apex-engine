# APEX 25.3 — VALIDATION

All results below were produced by executing the commands in this container.
No test count is asserted that was not actually run.

## Python compilation
`python3 -m py_compile` succeeded for all new/modified files.

## Test suite (actually executed)
- 25.3 module suite: **26 passed** (18 engine + 8 route).
- Complete repository suite after integration: **1156 passed, 0 failed**
  (`python3 -m pytest tests/ -q`) = prior 1130 baseline + 26 new. No regressions.

## Application import
- `import app` succeeds; no duplicate scanner start (scanner still gated on
  RUN_SCANNER_ON_IMPORT).
- Route map grew 640 -> 646 (+6 canonical 25.3 routes). verify_registered
  returns no missing routes; registration is fail-loud.
- Live smoke via test_client: status/current/curve/buckets/drift all 200.

## Routes registered (6)
- GET  /api/confidence-calibration/status
- GET  /api/confidence-calibration/current
- GET  /api/confidence-calibration/curve
- GET  /api/confidence-calibration/buckets
- GET  /api/confidence-calibration/drift
- POST /api/confidence-calibration/evaluate

## Database changes
- None. 25.3 reuses the existing 23.4 outcome store (apex_learning_outcomes_v234,
  DB_PATH). No new schema, no new database file.

## Environment-variable changes
- Added (both OPTIONAL, FEATURE_FLAGS, default 'false', safety_critical):
  APEX_CALIBRATION_PRODUCTION_ENABLED, APEX_CALIBRATION_PROMOTION_APPROVED.

## Shadow-mode status
- Enforced. `production_effect: NONE` on every payload. `shadow_mode()` returns
  True unless BOTH flags are set, and even then the engine only reports promotion
  readiness — it never writes production confidence.

## Ceiling invariant
- Asserted in `build_calibration` for historical/regime/execution/final layers
  and covered by `test_no_layer_exceeds_integrity_ceiling`.

## Known limitations
- Calibration reflects whatever graded outcomes exist in the 23.4 store; with a
  cold store it reports INSUFFICIENT_DATA and caps confidence conservatively.
- Isotonic calibration is intentionally not applied at current sample sizes; the
  engine uses bucketed empirical + Bayesian shrinkage until data supports more.
- No dashboard HTML panel ships (consistent with 25.0-25.2). `mission_control_group()`
  returns the canonical panel payload including the full confidence-layer stack.
