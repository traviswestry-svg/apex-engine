# APEX 26.0 — VALIDATION

All results below were produced by executing the commands in this container.
No test count is asserted that was not actually run.

## Python compilation
`python3 -m py_compile` succeeded for all new/modified files.

## Test suite (actually executed)
- 26.0 module suite: **28 passed** (engine + route).
- Complete repository suite after integration: **1243 passed, 1 failed**.
  * The single failure is `tests/test_refusal_replay_18_0_6.py::
    test_due_replay_is_idempotent_and_persists_scorecard`.
  * This failure is PRE-EXISTING and UNRELATED to 26.0. It reproduces
    identically on the untouched original repository (verified: full suite on
    pristine repo = 1 failed, 1101 passed). The test uses a self-contained
    tempdir DB and is timing/order-sensitive. 26.0 introduced ZERO new failures
    (+142 passing tests over the pristine baseline, same one flaky test).
  * Recommend addressing that test separately; it was intentionally NOT modified
    here to avoid masking any real issue inside an execution delta.

## Application import
- `import app` succeeds; no duplicate scanner start.
- Route map grew 671 -> 677 (+6 canonical routes). verify_registered returns no
  missing routes; registration is fail-loud.
- Live smoke: status/readiness/plan (GET) and size (POST) all 200.

## Routes registered (6, all advisory)
- GET  /api/execution/status
- GET  /api/execution/readiness
- GET  /api/execution/plan
- POST /api/execution/evaluate
- POST /api/execution/size
- POST /api/execution/grade

## Safety verified
- `places_orders` False and `production_effect` NONE on every response.
- No order-placement or broker-call code paths added.
- Position sizing never exceeds max_contracts and never exceeds
  max_risk_per_trade (tested); Kelly fraction capped at 0.25 and can only reduce
  size.
- Readiness always sets `requires_human_confirmation: true`; a wide spread or
  stale quote yields BLOCKED; a non-eligible decision yields NOT_READY.

## Database / environment changes
- None. Reuses existing TRADE_* risk-limit variables via RiskLimits.from_env().
