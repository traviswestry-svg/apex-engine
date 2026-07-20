# APEX 25.2 — VALIDATION

All results below were produced by executing the commands in this container.
No test count is asserted that was not actually run.

## Python compilation
`python3 -m py_compile` succeeded for all new/modified files:
- engine/decision_outcome_forecast_v252.py
- engine/decision_outcome_forecast_v252_routes.py
- engine/configuration_governance.py
- app.py
- tests/test_decision_outcome_forecast_v252.py
- tests/test_decision_outcome_forecast_v252_routes.py

## Test suite (actually executed)
- 25.2 module suite: **28 passed** (18 engine + 10 route).
- Complete repository suite after integration: **1130 passed, 0 failed**
  (`python3 -m pytest tests/ -q`). This is the prior baseline of 1102 passing
  tests plus the 28 new 25.2 tests. No pre-existing test regressed.

## Application import
- `import app` succeeds with no duplicate scanner start (scanner remains gated
  on RUN_SCANNER_ON_IMPORT).
- Route map grew from 634 to **640** (+6 canonical 25.2 routes). All routes
  register exactly once; `verify_registered` returns no missing routes.
- Live smoke via `app.test_client()`: `/status`, `/current`, `/scenarios` all 200.

## Routes registered (6)
- GET  /api/decision-forecast/status
- GET  /api/decision-forecast/current
- GET  /api/decision-forecast/scenarios
- GET  /api/decision-forecast/analogs
- GET  /api/decision-forecast/history
- POST /api/decision-forecast/evaluate

## Database changes
- New governed sqlite store `apex_decision_forecast.db` (env
  `APEX_DECISION_FORECAST_DB`), created lazily via `init_db()`; not created at
  import and not written to the repo root when the env var points elsewhere.
- Registered in `configuration_governance` so the env-drift guard passes.

## Environment-variable changes
- Added `APEX_DECISION_FORECAST_DB` (OPTIONAL, DATABASE, default
  `apex_decision_forecast.db`).

## Shadow-mode status
- Enforced. Every payload carries `production_effect: "NONE"` and a guardrails
  block; there is no code path from 25.2 to eligibility, confidence, weights, or
  order submission.

## Known limitations
- Analog magnitude uses provided `comparable_sessions`; when the live similarity
  engine feed is wired into `STATE["last_result"]`, no code change is required —
  the engine already reads `comparable_sessions`/`historical_similarity`.
- No dashboard HTML panel is shipped (consistent with 25.0/25.1, which are
  API + Mission Control only). `mission_control_group()` returns the canonical
  panel payload for the front-end to consume.
- Forecast evaluator requires realized-outcome truth to be supplied by the
  caller/replay harness; 25.2 does not itself watch live price.
